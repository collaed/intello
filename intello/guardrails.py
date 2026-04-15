"""Anti-hallucination guardrails — validates response confidence and flags issues."""
import re

# Hedging phrases that indicate low confidence
HEDGE_PATTERNS = [
    r"\bi(?:'m| am) not (?:sure|certain|confident)\b",
    r"\bi think\b.*\bbut\b",
    r"\bprobably\b.*\bmaybe\b",
    r"\bi don'?t (?:know|have|recall)\b",
    r"\bthis (?:might|may|could) (?:be|not be) (?:accurate|correct|right)\b",
    r"\bI cannot verify\b",
    r"\bas of my (?:last |knowledge )?(?:training|cutoff)\b",
    r"\bI (?:don'?t|do not) have (?:access to|real-time|current)\b",
]

# Patterns suggesting fabricated specifics
FABRICATION_SIGNALS = [
    r"\baccording to (?:a |the )?(?:recent )?(?:study|report|survey)\b(?!.*(?:http|www|\d{4}))",  # citation without source
    r"\bstatistics show that \d+%\b",  # specific stats without source
    r"\bresearch (?:shows|indicates|suggests) that\b(?!.*(?:http|www|\[))",
]


def check_confidence(response: str) -> dict:
    """Analyze response for hallucination signals. Returns confidence assessment."""
    text = response.lower()
    issues = []
    score = 1.0  # 1.0 = fully confident, 0.0 = no confidence

    # Check hedging
    hedge_count = 0
    for pattern in HEDGE_PATTERNS:
        matches = re.findall(pattern, text)
        hedge_count += len(matches)
    if hedge_count > 0:
        score -= min(0.3, hedge_count * 0.1)
        issues.append(f"Hedging language detected ({hedge_count} instances)")

    # Check fabrication signals
    fab_count = 0
    for pattern in FABRICATION_SIGNALS:
        matches = re.findall(pattern, text)
        fab_count += len(matches)
    if fab_count > 0:
        score -= min(0.3, fab_count * 0.15)
        issues.append(f"Unsourced claims detected ({fab_count} instances)")

    # Check for very short responses to complex questions
    word_count = len(response.split())
    if word_count < 20:
        score -= 0.1
        issues.append("Very short response")

    # Check for contradictions (simple: sentence says X then not X)
    sentences = re.split(r'[.!?]+', text)
    for i, s in enumerate(sentences):
        for j in range(i + 1, min(i + 3, len(sentences))):
            if "not" in sentences[j] and any(w in sentences[j] for w in s.split() if len(w) > 4):
                score -= 0.15
                issues.append("Possible self-contradiction")
                break

    score = max(0.0, min(1.0, score))
    return {
        "confidence": round(score, 2),
        "issues": issues,
        "needs_review": score < 0.6,
        "needs_reroute": score < 0.4,
    }


# --- Word Count Enforcement ---

def count_words(text: str) -> int:
    """Actual word count, stripping markup/code blocks."""
    clean = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # remove code blocks
    clean = re.sub(r'[#*_`~\[\]()>|]', ' ', clean)  # remove markdown
    return len(clean.split())


def check_word_count(text: str, target: int, tolerance: float = 0.15) -> dict:
    """Check if text meets a word count target within tolerance."""
    actual = count_words(text)
    ratio = actual / target if target > 0 else 1.0
    diff = actual - target
    pct = abs(diff) / target * 100 if target > 0 else 0

    ok = (1 - tolerance) <= ratio <= (1 + tolerance)
    return {
        "target": target,
        "actual": actual,
        "difference": diff,
        "percentage_off": round(pct, 1),
        "within_tolerance": ok,
        "verdict": "✅ On target" if ok else f"{'📈 Over' if diff > 0 else '📉 Under'} by {abs(diff)} words ({pct:.0f}%)",
    }
