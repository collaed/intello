"""NLP utilities — spaCy-based NER, sentence segmentation, and linguistic analysis."""
import functools

@functools.lru_cache(maxsize=1)
def _nlp():
    import spacy
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        from spacy.cli import download
        download("en_core_web_sm")
        return spacy.load("en_core_web_sm")


def extract_entities(text: str) -> dict[str, list[dict]]:
    """Extract named entities using spaCy NER. Returns {label: [{text, start, end}]}."""
    doc = _nlp()(text)
    entities: dict[str, list[dict]] = {}
    for ent in doc.ents:
        entities.setdefault(ent.label_, []).append({
            "text": ent.text, "start": ent.start_char, "end": ent.end_char,
        })
    return entities


def extract_characters(text: str) -> list[dict]:
    """Extract character names via NER (PERSON entities)."""
    doc = _nlp()(text)
    name_counts: dict[str, int] = {}
    name_lines: dict[str, list[int]] = {}

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            if len(name) > 1:
                name_counts[name] = name_counts.get(name, 0) + 1
                # Approximate line number from char offset
                line = text[:ent.start_char].count("\n") + 1
                name_lines.setdefault(name, []).append(line)

    # Merge variants (e.g. "Sarah" and "Sarah Chen")
    merged: dict[str, dict] = {}
    for name in sorted(name_counts, key=lambda n: -name_counts[n]):
        # Check if this is a substring of an already-seen name
        found = False
        for existing in merged:
            if name in existing or existing in name:
                merged[existing]["mentions"] += name_counts[name]
                merged[existing]["lines"].extend(name_lines.get(name, []))
                found = True
                break
        if not found and name_counts[name] >= 2:
            merged[name] = {
                "name": name,
                "mentions": name_counts[name],
                "lines": name_lines.get(name, []),
            }

    result = []
    for name, data in sorted(merged.items(), key=lambda x: -x[1]["mentions"]):
        lines = sorted(set(data["lines"]))
        result.append({
            "name": data["name"],
            "mentions": data["mentions"],
            "first_appearance": lines[0] if lines else 0,
            "last_appearance": lines[-1] if lines else 0,
            "lines": lines[:50],
        })
    return result


def segment_sentences(text: str) -> list[str]:
    """Split text into sentences using spaCy's sentence boundary detection."""
    doc = _nlp()(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def get_linguistic_features(text: str) -> dict:
    """Get linguistic features for a text passage."""
    doc = _nlp()(text)
    sents = list(doc.sents)
    if not sents:
        return {}

    sent_lengths = [len(s) for s in sents]
    pos_counts: dict[str, int] = {}
    for token in doc:
        pos_counts[token.pos_] = pos_counts.get(token.pos_, 0) + 1

    total = len(doc)
    return {
        "sentence_count": len(sents),
        "avg_sentence_length": sum(sent_lengths) / len(sents),
        "min_sentence_length": min(sent_lengths),
        "max_sentence_length": max(sent_lengths),
        "sentence_length_variance": (sum((l - sum(sent_lengths)/len(sents))**2 for l in sent_lengths) / len(sents)) ** 0.5,
        "noun_ratio": pos_counts.get("NOUN", 0) / total if total else 0,
        "verb_ratio": pos_counts.get("VERB", 0) / total if total else 0,
        "adj_ratio": pos_counts.get("ADJ", 0) / total if total else 0,
        "adv_ratio": pos_counts.get("ADV", 0) / total if total else 0,
    }
