"""Version reconstruction engine — rebuilds a complete document from scattered versioned files."""
import re
import json
import os
import time
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field

DB_PATH = os.environ.get("VERSIONS_DB", "/data/versions.db")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS version_projects (
                project_id TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS version_files (
                file_id TEXT PRIMARY KEY,
                project_id TEXT,
                version_label TEXT,
                version_num INTEGER,
                filename TEXT,
                content TEXT,
                sections JSON DEFAULT '[]',
                refs JSON DEFAULT '[]',
                ingested_at REAL
            );
            CREATE TABLE IF NOT EXISTS reconstructed (
                project_id TEXT,
                section_id TEXT,
                section_title TEXT,
                content TEXT,
                source_version TEXT,
                source_file TEXT,
                confidence TEXT DEFAULT 'high',
                notes TEXT DEFAULT '',
                PRIMARY KEY (project_id, section_id)
            );
        """)


_init()

# Patterns for detecting version references
VERSION_REF_PATTERNS = [
    r'(?:unchanged|inchangé|same as|voir|see|cf\.?|from)\s+(?:since\s+)?v(?:ersion)?\s*(\d+)',
    r'(?:as (?:in|per|defined in)|tel que dans)\s+v(?:ersion)?\s*(\d+)',
    r'v(\d+)\s+(?:section|chapter|part|chapitre)',
    r'(?:refer to|see|voir)\s+v(\d+)',
    r'\(v(\d+)\)',
    r'→\s*v(\d+)',
]

# Patterns for detecting section headers
SECTION_PATTERNS = [
    r'^#{1,4}\s+(.+)',                          # Markdown headers
    r'^(?:Section|Chapter|Part|Chapitre)\s+[\d.]+[:\s]+(.+)',
    r'^(\d+\.[\d.]*)\s+(.+)',                   # Numbered sections
    r'^([A-Z][A-Z\s]{3,})$',                    # ALL CAPS headers
    r'^(?:---+|===+)\s*$',                       # Horizontal rules (section break)
]


def extract_version_num(text: str) -> int | None:
    """Extract version number from filename or content."""
    m = re.search(r'v(?:ersion)?\s*(\d+)', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_sections(content: str) -> list[dict]:
    """Split content into sections with headers."""
    lines = content.split("\n")
    sections = []
    current_title = "Preamble"
    current_lines = []
    current_start = 0

    for i, line in enumerate(lines):
        is_header = False
        for pat in SECTION_PATTERNS:
            m = re.match(pat, line.strip())
            if m and len(line.strip()) < 200:  # headers shouldn't be too long
                if current_lines:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_lines).strip(),
                        "start_line": current_start,
                        "end_line": i - 1,
                    })
                current_title = line.strip()
                current_lines = []
                current_start = i
                is_header = True
                break
        if not is_header:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
            "start_line": current_start,
            "end_line": len(lines) - 1,
        })

    return sections


def find_references(content: str) -> list[dict]:
    """Find cross-version references in content."""
    refs = []
    for i, line in enumerate(content.split("\n")):
        for pat in VERSION_REF_PATTERNS:
            for m in re.finditer(pat, line, re.IGNORECASE):
                refs.append({
                    "line": i,
                    "text": line.strip(),
                    "referenced_version": int(m.group(1)),
                    "pattern": pat,
                })
    return refs


def create_version_project(project_id: str, name: str) -> dict:
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO version_projects (project_id, name, created_at) VALUES (?,?,?)",
                     (project_id, name, time.time()))
    return {"project_id": project_id, "name": name}


def ingest_version(project_id: str, filename: str, content: str) -> dict:
    """Ingest a version file — parse sections and references."""
    version_num = extract_version_num(filename) or extract_version_num(content[:500])
    version_label = f"v{version_num}" if version_num else filename

    sections = parse_sections(content)
    refs = find_references(content)

    file_id = f"{project_id}_{version_label}_{int(time.time())}"

    with _db() as conn:
        conn.execute("""INSERT OR REPLACE INTO version_files
                        (file_id, project_id, version_label, version_num, filename, content, sections, refs, ingested_at)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (file_id, project_id, version_label, version_num or 0, filename, content,
                      json.dumps([{k: v for k, v in s.items() if k != "content"} for s in sections]),
                      json.dumps(refs), time.time()))

    return {
        "file_id": file_id,
        "version": version_label,
        "version_num": version_num,
        "sections": len(sections),
        "refs": len(refs),
        "section_titles": [s["title"] for s in sections],
    }


def get_project_versions(project_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT file_id, version_label, version_num, filename, sections, refs FROM version_files WHERE project_id=? ORDER BY version_num",
            (project_id,)).fetchall()
    return [{**dict(r), "sections": json.loads(r["sections"]), "refs": json.loads(r["refs"])} for r in rows]


def reconstruct(project_id: str) -> dict:
    """
    Reconstruct a complete document from all versions.
    Strategy:
    1. Build a section inventory across all versions
    2. For each section, use the LATEST version that has actual content (not a reference)
    3. For sections with references ("unchanged since vN"), pull from version N
    4. Flag gaps and conflicts
    """
    with _db() as conn:
        files = conn.execute(
            "SELECT * FROM version_files WHERE project_id=? ORDER BY version_num",
            (project_id,)).fetchall()

    if not files:
        return {"error": "No versions ingested"}

    # Build section inventory: {section_title: [{version, content, is_reference, ref_version}]}
    inventory: dict[str, list[dict]] = {}
    all_refs: list[dict] = []

    for f in files:
        sections = parse_sections(f["content"])
        refs = json.loads(f["refs"])
        all_refs.extend([{**r, "in_version": f["version_num"]} for r in refs])

        for s in sections:
            # Check if this section is just a reference to another version
            is_ref = False
            ref_version = None
            for ref in refs:
                if ref["line"] >= s["start_line"] and ref["line"] <= s["end_line"]:
                    is_ref = True
                    ref_version = ref["referenced_version"]
                    break

            # Skip near-empty sections (just a reference line)
            has_content = len(s["content"].strip()) > 50

            inventory.setdefault(s["title"], []).append({
                "version_num": f["version_num"],
                "version_label": f["version_label"],
                "filename": f["filename"],
                "content": s["content"],
                "is_reference": is_ref and not has_content,
                "ref_version": ref_version,
                "has_content": has_content,
            })

    # Reconstruct: for each section, pick the best source
    reconstructed = []
    gaps = []
    conflicts = []

    with _db() as conn:
        conn.execute("DELETE FROM reconstructed WHERE project_id=?", (project_id,))

        for title, versions in inventory.items():
            # Sort by version number descending
            versions.sort(key=lambda v: v["version_num"], reverse=True)

            chosen = None
            source = ""
            confidence = "high"
            notes = ""

            # Strategy 1: Use latest version with actual content
            for v in versions:
                if v["has_content"] and not v["is_reference"]:
                    chosen = v["content"]
                    source = v["version_label"]
                    break

            # Strategy 2: Follow reference chain
            if not chosen:
                for v in versions:
                    if v["is_reference"] and v["ref_version"]:
                        # Find the referenced version
                        for v2 in versions:
                            if v2["version_num"] == v["ref_version"] and v2["has_content"]:
                                chosen = v2["content"]
                                source = f"{v2['version_label']} (referenced from {v['version_label']})"
                                confidence = "medium"
                                notes = f"Content pulled from {v2['version_label']} via reference in {v['version_label']}"
                                break
                    if chosen:
                        break

            # Strategy 3: Use whatever we have
            if not chosen:
                for v in versions:
                    if v["content"].strip():
                        chosen = v["content"]
                        source = f"{v['version_label']} (best available)"
                        confidence = "low"
                        notes = "No definitive version found, using best available"
                        break

            if chosen:
                section_id = re.sub(r'[^a-z0-9]', '_', title.lower())[:50]
                conn.execute("""INSERT OR REPLACE INTO reconstructed
                                (project_id, section_id, section_title, content, source_version, source_file, confidence, notes)
                                VALUES (?,?,?,?,?,?,?,?)""",
                             (project_id, section_id, title, chosen, source, "", confidence, notes))
                reconstructed.append({
                    "section": title,
                    "source": source,
                    "confidence": confidence,
                    "notes": notes,
                    "words": len(chosen.split()),
                })
            else:
                gaps.append({"section": title, "reason": "No content found in any version"})

    total_words = sum(s["words"] for s in reconstructed)
    return {
        "sections": len(reconstructed),
        "total_words": total_words,
        "gaps": gaps,
        "conflicts": conflicts,
        "reconstruction": reconstructed,
        "versions_used": list({s["source"] for s in reconstructed}),
    }


def get_reconstructed_text(project_id: str) -> str:
    """Get the full reconstructed document as text."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT section_title, content, source_version, confidence FROM reconstructed WHERE project_id=? ORDER BY rowid",
            (project_id,)).fetchall()
    parts = []
    for r in rows:
        parts.append(f"{r['section_title']}\n\n{r['content']}")
    return "\n\n---\n\n".join(parts)


def list_version_projects() -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM version_projects ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
