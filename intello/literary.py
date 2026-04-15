"""Literary engine — document ingestion, structural analysis, pacing, and surgical editing."""
import os
import re
import sqlite3
import time
import json
from contextlib import contextmanager
from dataclasses import dataclass, field

DB_PATH = os.environ.get("LITERARY_DB", "/data/literary.db")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                title TEXT,
                genre TEXT DEFAULT 'fiction',
                brief TEXT DEFAULT '',
                target_words INTEGER DEFAULT 0,
                style TEXT DEFAULT '',
                steps JSON DEFAULT '[]',
                detected_style TEXT DEFAULT '',
                detected_intent TEXT DEFAULT '',
                character_arcs JSON DEFAULT '[]',
                themes JSON DEFAULT '[]',
                setting TEXT DEFAULT '',
                tone TEXT DEFAULT '',
                pov TEXT DEFAULT '',
                audience TEXT DEFAULT '',
                iteration_state JSON DEFAULT '{}',
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                project_id TEXT DEFAULT '',
                title TEXT,
                total_lines INTEGER,
                total_words INTEGER,
                total_tokens INTEGER,
                metadata JSON DEFAULT '{}',
                created_at REAL
            );"""
        # rest of tables...
        + """
            CREATE TABLE IF NOT EXISTS lines (
                doc_id TEXT, line_num INTEGER,
                text TEXT,
                chapter TEXT DEFAULT '',
                scene TEXT DEFAULT '',
                PRIMARY KEY (doc_id, line_num)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT,
                chapter TEXT,
                start_line INTEGER, end_line INTEGER,
                token_count INTEGER,
                text TEXT
            );
            CREATE TABLE IF NOT EXISTS doc_map (
                doc_id TEXT, entity_type TEXT, entity_id TEXT,
                start_line INTEGER, end_line INTEGER,
                metadata JSON DEFAULT '{}',
                PRIMARY KEY (doc_id, entity_type, entity_id)
            );
            CREATE TABLE IF NOT EXISTS pacing (
                doc_id TEXT, line_num INTEGER,
                sentence_len REAL, word_len REAL,
                dialogue INTEGER DEFAULT 0,
                tension REAL DEFAULT 0,
                PRIMARY KEY (doc_id, line_num)
            );
            CREATE TABLE IF NOT EXISTS edits (
                edit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                edit_type TEXT,
                start_line INTEGER, end_line INTEGER,
                original TEXT, replacement TEXT,
                reason TEXT, model TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS versions (
                version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT, parent_version INTEGER,
                changes JSON, created_at REAL
            );
        """)
        # Migrate: add project_id column if missing
        try:
            conn.execute("SELECT project_id FROM documents LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE documents ADD COLUMN project_id TEXT DEFAULT ''")


_init()


# --- Projects ---

def create_project(project_id: str, title: str, genre: str = "fiction", brief: str = "",
                   target_words: int = 0, style: str = "", steps: list[str] | None = None,
                   **extra) -> dict:
    now = time.time()
    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO projects
                        (project_id, title, genre, brief, target_words, style, steps,
                         detected_style, detected_intent, character_arcs, themes,
                         setting, tone, pov, audience, iteration_state, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (project_id, title, genre, brief, target_words, style,
                      json.dumps(steps or []),
                      extra.get("detected_style", ""),
                      extra.get("detected_intent", ""),
                      json.dumps(extra.get("character_arcs", [])),
                      json.dumps(extra.get("themes", [])),
                      extra.get("setting", ""),
                      extra.get("tone", ""),
                      extra.get("pov", ""),
                      extra.get("audience", ""),
                      json.dumps(extra.get("iteration_state", {})),
                      now, now))
    return get_project(project_id)


def get_project(project_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("steps", "character_arcs", "themes", "iteration_state"):
        try:
            d[k] = json.loads(d[k]) if d[k] else ([] if k != "iteration_state" else {})
        except (json.JSONDecodeError, TypeError):
            d[k] = [] if k != "iteration_state" else {}
    return d


def update_project(project_id: str, **kwargs) -> dict | None:
    allowed = {"title", "genre", "brief", "target_words", "style", "steps",
               "detected_style", "detected_intent", "character_arcs", "themes",
               "setting", "tone", "pov", "audience", "iteration_state"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return get_project(project_id)
    for k in ("steps", "character_arcs", "themes", "iteration_state"):
        if k in updates and isinstance(updates[k], (list, dict)):
            updates[k] = json.dumps(updates[k])
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [time.time(), project_id]
    with _db() as conn:
        conn.execute(f"UPDATE projects SET {sets}, updated_at=? WHERE project_id=?", vals)
    return get_project(project_id)


def list_projects() -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for k in ("steps", "character_arcs", "themes", "iteration_state"):
            try:
                d[k] = json.loads(d[k]) if d[k] else ([] if k != "iteration_state" else {})
            except (json.JSONDecodeError, TypeError):
                d[k] = [] if k != "iteration_state" else {}
        result.append(d)
    return result


def link_document_to_project(doc_id: str, project_id: str):
    with _db() as conn:
        conn.execute("UPDATE documents SET project_id=? WHERE doc_id=?", (project_id, doc_id))


def get_project_brief_prompt(project_id: str) -> str:
    """Build a context string from the project brief for LLM prompts."""
    p = get_project(project_id)
    if not p:
        return ""
    parts = [f"PROJECT: \"{p['title']}\""]
    parts.append(f"Genre: {p['genre']}")
    if p.get("brief"):
        parts.append(f"Brief: {p['brief']}")
    if p.get("target_words"):
        parts.append(f"Target length: {p['target_words']} words")
    if p.get("style"):
        parts.append(f"Target style: {p['style']}")
    if p.get("detected_style"):
        parts.append(f"Detected writing style: {p['detected_style']}")
    if p.get("detected_intent"):
        parts.append(f"Author's intent: {p['detected_intent']}")
    if p.get("tone"):
        parts.append(f"Tone: {p['tone']}")
    if p.get("pov"):
        parts.append(f"Point of view: {p['pov']}")
    if p.get("setting"):
        parts.append(f"Setting: {p['setting']}")
    if p.get("audience"):
        parts.append(f"Target audience: {p['audience']}")
    if p.get("character_arcs"):
        parts.append("Character arcs:")
        for c in p["character_arcs"]:
            if isinstance(c, dict):
                parts.append(f"  - {c.get('name','?')}: {c.get('arc','?')}")
            else:
                parts.append(f"  - {c}")
    if p.get("themes"):
        parts.append(f"Themes: {', '.join(p['themes'])}")
    if p.get("steps"):
        parts.append("Key steps/milestones:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(p["steps"])))
    return "\n".join(parts)


# --- Document Ingestion ---

CHAPTER_PATTERNS = [
    r'^(?:CHAPTER|Chapter|PART|Part|ACT|Act)\s+[\dIVXLCDMivxlcdm]+',
    r'^(?:CHAPTER|Chapter|PART|Part|ACT|Act)\s+\w+',
    r'^\d+\.\s+\w',  # "1. Title"
    r'^#{1,3}\s+',   # Markdown headers
]


def ingest_document(doc_id: str, text: str, title: str = "", project_id: str = "") -> dict:
    """Ingest a document: split into lines, detect structure, compute pacing."""
    raw_lines = text.split("\n")

    with _db() as conn:
        # Store document
        conn.execute("DELETE FROM lines WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM doc_map WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM pacing WHERE doc_id=?", (doc_id,))

        # Store lines with chapter detection
        current_chapter = "Preamble"
        chapter_num = 0
        chapters = []

        for i, line in enumerate(raw_lines, 1):
            is_chapter = False
            for pat in CHAPTER_PATTERNS:
                if re.match(pat, line.strip()):
                    chapter_num += 1
                    current_chapter = line.strip()
                    is_chapter = True
                    chapters.append({"chapter": current_chapter, "start_line": i})
                    break

            conn.execute("INSERT INTO lines (doc_id, line_num, text, chapter) VALUES (?,?,?,?)",
                         (doc_id, i, line, current_chapter))

        # Set chapter end lines
        for j, ch in enumerate(chapters):
            end = chapters[j + 1]["start_line"] - 1 if j + 1 < len(chapters) else len(raw_lines)
            conn.execute("INSERT OR REPLACE INTO doc_map (doc_id, entity_type, entity_id, start_line, end_line, metadata) VALUES (?,?,?,?,?,?)",
                         (doc_id, "chapter", f"ch_{j+1}", ch["start_line"], end,
                          json.dumps({"title": ch["chapter"]})))

        # Create chunks (~2000 tokens each, respecting chapter boundaries)
        chunk_lines = []
        chunk_start = 1
        chunk_chapter = current_chapter
        chunk_num = 0

        for i, line in enumerate(raw_lines, 1):
            chunk_lines.append(line)
            token_est = sum(len(l.split()) for l in chunk_lines) * 1.3

            # Break on chapter boundary or token limit
            new_chapter = any(re.match(p, line.strip()) for p in CHAPTER_PATTERNS)
            if token_est > 2000 or (new_chapter and len(chunk_lines) > 1) or i == len(raw_lines):
                chunk_num += 1
                chunk_text = "\n".join(chunk_lines)
                conn.execute("INSERT INTO chunks (chunk_id, doc_id, chapter, start_line, end_line, token_count, text) VALUES (?,?,?,?,?,?,?)",
                             (f"{doc_id}:chunk_{chunk_num}", doc_id, chunk_chapter,
                              chunk_start, i, int(token_est), chunk_text))
                chunk_lines = []
                chunk_start = i + 1

        # Compute pacing metrics per line using textstat + heuristics
        import textstat
        for i, line in enumerate(raw_lines, 1):
            words = line.split()
            if not words:
                conn.execute("INSERT INTO pacing (doc_id, line_num, sentence_len, word_len, dialogue, tension) VALUES (?,?,?,?,?,?)",
                             (doc_id, i, 0, 0, 0, 0))
                continue

            # Readability as proxy for complexity
            try:
                reading_ease = textstat.flesch_reading_ease(line) if len(words) > 5 else 50
            except Exception:
                reading_ease = 50

            avg_word_len = sum(len(w) for w in words) / len(words)
            is_dialogue = 1 if re.search(r'["""\u201c\u201d\'].*?["""\u201c\u201d\']', line) or line.strip().startswith(('-', '\u2014', '"', '\u201c')) else 0

            # Tension: short sentences + action words + low reading ease
            tension_words = {"suddenly", "screamed", "ran", "blood", "death", "fire", "crash",
                             "fight", "knife", "gun", "dark", "fear", "heart", "fast", "broke",
                             "slammed", "shouted", "exploded", "silence", "shadow", "gasped",
                             "froze", "shattered", "ripped", "lunged", "collapsed", "trembled"}
            tension = sum(1 for w in words if w.lower().strip(".,!?") in tension_words)
            # Short lines with many words = punchy = tense
            avg_sent_len = len(words)  # approximate for single line
            if avg_sent_len < 8 and len(words) > 3:
                tension += 1
            # Low reading ease = complex/tense prose
            if reading_ease < 30 and len(words) > 5:
                tension += 0.5

            conn.execute("INSERT INTO pacing (doc_id, line_num, sentence_len, word_len, dialogue, tension) VALUES (?,?,?,?,?,?)",
                         (doc_id, i, avg_sent_len, avg_word_len, is_dialogue, tension))

        total_words = sum(len(l.split()) for l in raw_lines)
        conn.execute("INSERT OR REPLACE INTO documents (doc_id, project_id, title, total_lines, total_words, total_tokens, created_at) VALUES (?,?,?,?,?,?,?)",
                     (doc_id, project_id, title or doc_id, len(raw_lines), total_words, int(total_words * 1.3), time.time()))

    chars = extract_characters(doc_id)
    threads = extract_threads(doc_id)
    return {
        "doc_id": doc_id, "title": title, "lines": len(raw_lines),
        "words": total_words, "chapters": len(chapters), "chunks": chunk_num,
        "characters": len(chars), "threads": len(threads),
    }


# --- Querying ---

def get_document_info(doc_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return dict(row) if row else None


def get_structure(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM doc_map WHERE doc_id=? AND entity_type='chapter' ORDER BY start_line", (doc_id,)).fetchall()
    return [dict(r) for r in rows]


def get_lines(doc_id: str, start: int, end: int) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM lines WHERE doc_id=? AND line_num BETWEEN ? AND ? ORDER BY line_num",
                            (doc_id, start, end)).fetchall()
    return [dict(r) for r in rows]


def get_chunk(chunk_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    return dict(row) if row else None


def get_chunks(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT chunk_id, chapter, start_line, end_line, token_count FROM chunks WHERE doc_id=? ORDER BY start_line", (doc_id,)).fetchall()
    return [dict(r) for r in rows]


def get_pacing_data(doc_id: str, window: int = 50) -> list[dict]:
    """Get pacing data averaged over a sliding window."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM pacing WHERE doc_id=? ORDER BY line_num", (doc_id,)).fetchall()
    if not rows:
        return []

    data = [dict(r) for r in rows]
    result = []
    for i in range(0, len(data), window):
        batch = data[i:i + window]
        result.append({
            "start_line": batch[0]["line_num"],
            "end_line": batch[-1]["line_num"],
            "avg_sentence_len": sum(b["sentence_len"] for b in batch) / len(batch),
            "dialogue_ratio": sum(b["dialogue"] for b in batch) / len(batch),
            "tension": sum(b["tension"] for b in batch) / len(batch),
        })
    return result


# --- Surgical Edits ---

def propose_edit(doc_id: str, edit_type: str, start_line: int, end_line: int,
                 replacement: str, reason: str, model: str) -> int:
    """Propose an edit. Returns edit_id."""
    with _db() as conn:
        # Get original text
        rows = conn.execute("SELECT text FROM lines WHERE doc_id=? AND line_num BETWEEN ? AND ? ORDER BY line_num",
                            (doc_id, start_line, end_line)).fetchall()
        original = "\n".join(r["text"] for r in rows)

        conn.execute("INSERT INTO edits (doc_id, edit_type, start_line, end_line, original, replacement, reason, model, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (doc_id, edit_type, start_line, end_line, original, replacement, reason, model, time.time()))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_pending_edits(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM edits WHERE doc_id=? AND status='pending' ORDER BY start_line", (doc_id,)).fetchall()
    return [dict(r) for r in rows]


def apply_edit(edit_id: int) -> bool:
    """Apply a pending edit to the document."""
    with _db() as conn:
        edit = conn.execute("SELECT * FROM edits WHERE edit_id=?", (edit_id,)).fetchone()
        if not edit or edit["status"] != "pending":
            return False

        new_lines = edit["replacement"].split("\n")
        doc_id = edit["doc_id"]

        # Delete old lines in range
        conn.execute("DELETE FROM lines WHERE doc_id=? AND line_num BETWEEN ? AND ?",
                     (doc_id, edit["start_line"], edit["end_line"]))

        # Shift subsequent lines
        old_count = edit["end_line"] - edit["start_line"] + 1
        new_count = len(new_lines)
        shift = new_count - old_count

        if shift != 0:
            conn.execute("UPDATE lines SET line_num = line_num + ? WHERE doc_id=? AND line_num > ?",
                         (shift, doc_id, edit["end_line"]))

        # Insert new lines
        for i, text in enumerate(new_lines):
            conn.execute("INSERT INTO lines (doc_id, line_num, text) VALUES (?,?,?)",
                         (doc_id, edit["start_line"] + i, text))

        conn.execute("UPDATE edits SET status='applied' WHERE edit_id=?", (edit_id,))

        # Version history
        conn.execute("INSERT INTO versions (doc_id, changes, created_at) VALUES (?,?,?)",
                     (doc_id, json.dumps({"edit_id": edit_id, "type": edit["edit_type"],
                                          "lines": f"{edit['start_line']}-{edit['end_line']}"}),
                      time.time()))
    return True


def reject_edit(edit_id: int):
    with _db() as conn:
        conn.execute("UPDATE edits SET status='rejected' WHERE edit_id=?", (edit_id,))


# --- Character Extraction ---

def extract_characters(doc_id: str) -> list[dict]:
    """Extract character names using spaCy NER."""
    from . import nlp as nlp_mod

    full_text = get_full_text(doc_id)
    characters = nlp_mod.extract_characters(full_text)

    # Store in doc_map
    with _db() as conn:
        conn.execute("DELETE FROM doc_map WHERE doc_id=? AND entity_type='character'", (doc_id,))
        for ch in characters:
            conn.execute("INSERT INTO doc_map (doc_id, entity_type, entity_id, start_line, end_line, metadata) VALUES (?,?,?,?,?,?)",
                         (doc_id, "character", f"char_{ch['name'].lower().replace(' ','_')}",
                          ch["first_appearance"], ch["last_appearance"],
                          json.dumps({"name": ch["name"], "mentions": ch["mentions"], "lines": ch["lines"][:50]})))

    return characters


def get_characters(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM doc_map WHERE doc_id=? AND entity_type='character' ORDER BY start_line", (doc_id,)).fetchall()
    return [{"name": json.loads(r["metadata"])["name"],
             "mentions": json.loads(r["metadata"])["mentions"],
             "first_line": r["start_line"], "last_line": r["end_line"]}
            for r in rows]


# --- Full Document Text ---

def get_full_text(doc_id: str) -> str:
    with _db() as conn:
        rows = conn.execute("SELECT text FROM lines WHERE doc_id=? ORDER BY line_num", (doc_id,)).fetchall()
    return "\n".join(r["text"] for r in rows)


def get_text_range(doc_id: str, start: int, end: int) -> str:
    with _db() as conn:
        rows = conn.execute("SELECT text FROM lines WHERE doc_id=? AND line_num BETWEEN ? AND ? ORDER BY line_num",
                            (doc_id, start, end)).fetchall()
    return "\n".join(r["text"] for r in rows)


# --- PDF/EPUB Ingestion ---

def ingest_pdf(doc_id: str, pdf_path: str, title: str = "", project_id: str = "") -> dict:
    """Ingest a PDF file — extract text via pymupdf, then process as document."""
    import fitz  # pymupdf
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    text = "\n\n".join(pages)
    return ingest_document(doc_id, text, title or pdf_path, project_id)


def ingest_epub(doc_id: str, epub_path: str, title: str = "", project_id: str = "") -> dict:
    """Ingest an EPUB file — extract text, then process as document."""
    import zipfile
    from html.parser import HTMLParser

    class _Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, d):
            self.parts.append(d)
        def get_text(self):
            return "".join(self.parts)

    text_parts = []
    with zipfile.ZipFile(epub_path) as z:
        for name in sorted(z.namelist()):
            if name.endswith((".xhtml", ".html", ".htm")):
                html = z.read(name).decode("utf-8", errors="replace")
                s = _Strip()
                s.feed(html)
                t = s.get_text().strip()
                if t:
                    text_parts.append(t)

    text = "\n\n".join(text_parts)
    return ingest_document(doc_id, text, title or epub_path, project_id)


# --- Narrative Threads / Open Questions ---

MYSTERY_SIGNALS = [
    (r'\bwho\b.*\?', "identity"),
    (r'\bwhy\b.*\?', "motive"),
    (r'\bwhat\b.*\?', "event"),
    (r'\bhow\b.*\?', "method"),
    (r'\bwhere\b.*\?', "location"),
    (r'\bwhen\b.*\?', "timing"),
    (r'\bwhat happens\b', "suspense"),
    (r'\bsecret\b', "secret"),
    (r'\bmystery\b|\bmysterious\b', "mystery"),
    (r'\bhiding\b|\bhidden\b', "concealment"),
    (r'\blie\b|\blied\b|\blying\b', "deception"),
    (r'\bwonder(?:ed|ing)?\b', "curiosity"),
    (r'\bstrange\b|\bodd\b|\bweird\b', "anomaly"),
    (r'\bwhat (?:do|did|will|would|could|should)\b', "decision"),
    (r'\bdon\'?t (?:know|understand)\b', "unknown"),
    (r'\bnot (?:yet|sure|certain)\b', "uncertainty"),
    (r'\bwaiting\b|\bsuspense\b', "suspense"),
    (r'\bthreat\b|\bdanger\b|\brisk\b', "threat"),
    (r'\bpromise\b|\bswore\b|\bswear\b', "promise"),
    (r'\bclue\b|\bevidence\b|\bproof\b', "investigation"),
]

RESOLUTION_SIGNALS = [
    r'\brevealed\b|\breveal\b',
    r'\bturns out\b|\bturned out\b',
    r'\bfinally\b.*\b(?:knew|understood|realized|discovered|found)\b',
    r'\bthe (?:truth|answer|reason|explanation)\b',
    r'\bnow (?:I|she|he|they|we) (?:knew|know|understood|understand)\b',
    r'\bit was\b.*\ball along\b',
    r'\bconfessed\b|\badmitted\b',
    r'\bsolved\b|\bresolved\b',
    r'\bat last\b',
]


def extract_threads(doc_id: str) -> list[dict]:
    """Extract narrative threads — open questions, mysteries, unresolved tensions."""
    with _db() as conn:
        rows = conn.execute("SELECT line_num, text FROM lines WHERE doc_id=? ORDER BY line_num",
                            (doc_id,)).fetchall()
        total = conn.execute("SELECT total_lines FROM documents WHERE doc_id=?",
                             (doc_id,)).fetchone()

    if not rows or not total:
        return []

    total_lines = total["total_lines"]
    threads = []

    for row in rows:
        text = row["text"].lower()
        for pattern, category in MYSTERY_SIGNALS:
            if re.search(pattern, text):
                # Found an open question — estimate where it resolves
                resolve_line = None
                # Scan forward for resolution signals
                for fwd in rows:
                    if fwd["line_num"] <= row["line_num"]:
                        continue
                    fwd_text = fwd["text"].lower()
                    for res_pat in RESOLUTION_SIGNALS:
                        if re.search(res_pat, fwd_text):
                            resolve_line = fwd["line_num"]
                            break
                    if resolve_line:
                        break

                # Build a short description from the source line
                desc = row["text"].strip()[:120]
                if len(row["text"].strip()) > 120:
                    desc += "…"

                threads.append({
                    "category": category,
                    "start_line": row["line_num"],
                    "end_line": resolve_line or total_lines,
                    "resolved": resolve_line is not None,
                    "description": desc,
                    "intensity": 1.0 if not resolve_line else 0.7,  # unresolved = higher intensity
                })
                break  # one thread per line max

    # Deduplicate overlapping threads of same category
    seen = set()
    unique = []
    for t in threads:
        key = (t["category"], t["start_line"])
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # Store in doc_map
    with _db() as conn:
        conn.execute("DELETE FROM doc_map WHERE doc_id=? AND entity_type='thread'", (doc_id,))
        for i, t in enumerate(unique):
            conn.execute("INSERT INTO doc_map (doc_id, entity_type, entity_id, start_line, end_line, metadata) VALUES (?,?,?,?,?,?)",
                         (doc_id, "thread", f"thread_{i}", t["start_line"], t["end_line"],
                          json.dumps(t)))

    return unique


def get_threads(doc_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT metadata FROM doc_map WHERE doc_id=? AND entity_type='thread' ORDER BY start_line",
                            (doc_id,)).fetchall()
    return [json.loads(r["metadata"]) for r in rows]
