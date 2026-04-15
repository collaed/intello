"""Literary reference engine — dynamically fetches craft techniques and examples."""

# Curated craft knowledge organized by need, not by book.
# The system picks relevant techniques based on the current writing situation.

FICTION_TECHNIQUES = {
    "tension_building": [
        "Short sentences accelerate pace. Hemingway's 'Hills Like White Elephants' — almost entirely dialogue, tension from what's NOT said.",
        "Withhold information the reader wants. Hitchcock's bomb-under-the-table: the audience knows, the characters don't.",
        "Interrupt a scene at its peak. Cut away. Return later. The reader's imagination fills the gap with dread.",
        "Use concrete sensory details when tension rises — the smell of copper, the sound of breathing. Abstract language kills tension.",
        "Compress time during action (short sentences, present tense feel). Expand time during suspense (long descriptions of small moments).",
    ],
    "character_depth": [
        "Characters reveal themselves through choices under pressure, not through description. What do they do when nobody's watching?",
        "Give every character a contradiction — the brave man who's afraid of dogs, the liar who keeps one sacred truth.",
        "Dialogue should do double duty: advance plot AND reveal character. If it only does one, cut it.",
        "Show the character's specific knowledge — a carpenter notices joints, a chef notices smells. Expertise makes characters real.",
        "The best villains believe they're the hero of their own story. Give them a logic that makes sense from their perspective.",
    ],
    "pacing_slow": [
        "Your scene is dragging because nothing is at stake. Add a ticking clock, a secret about to be revealed, or a decision that can't be postponed.",
        "Cut the throat-clearing. Most scenes start too early. Enter late, leave early.",
        "Replace description with action that reveals the same information. Don't describe the room — have the character interact with it.",
        "If two scenes do the same emotional work, merge them. Redundancy is the enemy of pace.",
        "Dialogue without subtext is dead air. Every conversation should have an undercurrent — what they really mean vs. what they say.",
    ],
    "pacing_fast": [
        "Your action scene needs breathing room. Insert a moment of stillness — a detail, a memory, a sensory pause — before the next beat.",
        "Vary sentence length. All-short-sentences reads like a telegram. Mix a long flowing sentence between the punches.",
        "Ground fast scenes in physical reality. Where are the characters' bodies? What do they touch, smell, hear?",
        "After a climactic moment, give the reader (and character) time to process. The aftermath is where meaning lives.",
    ],
    "prose_quality": [
        "Kill adverbs. 'She said angrily' → 'She slammed her fist on the table.' Show the anger, don't label it.",
        "Avoid the verb 'to be' where possible. 'The room was dark' → 'Darkness swallowed the room.' Active voice creates energy.",
        "Read your prose aloud. If you stumble, the reader will too. Rhythm matters as much as meaning.",
        "Specific beats general. Not 'a tree' but 'a sycamore.' Not 'a car' but 'a rusted Citroën.' Specificity creates belief.",
        "First and last sentences of chapters carry disproportionate weight. Make them count.",
    ],
    "structure": [
        "Every chapter should turn something — a revelation, a decision, a shift in power. If nothing turns, the chapter is a scene, not a chapter.",
        "The three-act structure is a floor, not a ceiling. Setup (25%), Confrontation (50%), Resolution (25%) — but break it knowingly.",
        "Subplots should mirror or contrast the main plot thematically. If the main plot is about trust, the subplot should test trust differently.",
        "Plant and payoff: introduce elements early that become crucial later. Chekhov's gun, but also Chekhov's emotion, Chekhov's relationship.",
    ],
    "opening": [
        "Start with a character in motion — physically or emotionally. Static openings lose readers.",
        "The first page makes a promise to the reader about what kind of book this is. Don't break that promise.",
        "Raise a question in the first paragraph that the reader needs answered. Not a mystery necessarily — just curiosity.",
    ],
}

NONFICTION_TECHNIQUES = {
    "explanation": [
        "Start with what the reader already knows, then bridge to the unknown. Analogy is your most powerful tool.",
        "The Feynman technique: if you can't explain it simply, you don't understand it well enough. Simplify, then add nuance.",
        "Layer complexity: first pass gives the intuition, second pass adds precision, third pass handles edge cases.",
        "Use concrete examples before abstract principles. The example IS the explanation; the principle is just the label.",
        "Anticipate the reader's 'but what about...' and address it before they think it. This builds trust.",
    ],
    "argument": [
        "Steel-man the opposing view before dismantling it. Readers trust writers who take counterarguments seriously.",
        "One claim per paragraph. Support it. Move on. Mixing claims creates confusion, not complexity.",
        "Data without narrative is forgettable. Wrap statistics in human stories.",
        "The strongest position in any argument is the one that acknowledges its own limitations.",
    ],
    "structure": [
        "Non-fiction chapters should each answer one question the reader has after the previous chapter.",
        "The inverted pyramid: most important insight first, supporting detail after. Respect the reader's time.",
        "Use signposting: tell them what you'll tell them, tell them, tell them what you told them. It's not redundant — it's architecture.",
        "Transitions between sections should create a sense of inevitability — 'of course this leads to that.'",
    ],
    "engagement": [
        "Open chapters with a scene, not a thesis. Narrative non-fiction outsells academic non-fiction for a reason.",
        "Ask questions the reader is already thinking. Then answer them in unexpected ways.",
        "Vary your evidence types: anecdote, data, expert quote, historical parallel. Monotony of evidence bores even interested readers.",
        "End chapters with a hook — an unresolved tension, a provocative question, a cliffhanger fact.",
    ],
}


def get_relevant_techniques(genre: str, issues: list[str], style: str = "") -> list[str]:
    """Dynamically select relevant craft techniques based on the current writing situation."""
    bank = FICTION_TECHNIQUES if genre in ("fiction", "screenplay", "poetry") else NONFICTION_TECHNIQUES
    selected = []

    # Map issues to technique categories
    issue_map = {
        "slow": ["pacing_slow", "engagement"],
        "fast": ["pacing_fast"],
        "tension": ["tension_building"],
        "character": ["character_depth"],
        "prose": ["prose_quality"],
        "structure": ["structure"],
        "opening": ["opening"],
        "explanation": ["explanation"],
        "argument": ["argument"],
        "flat": ["tension_building", "character_depth"],
        "boring": ["pacing_slow", "engagement", "prose_quality"],
        "confusing": ["structure", "explanation"],
        "wordy": ["prose_quality", "pacing_slow"],
    }

    matched_categories = set()
    for issue in issues:
        issue_lower = issue.lower()
        for keyword, categories in issue_map.items():
            if keyword in issue_lower:
                matched_categories.update(categories)

    # If no specific issues matched, give general craft advice
    if not matched_categories:
        matched_categories = {"prose_quality", "structure"}

    # Pull 2-3 techniques from each matched category
    import random
    for cat in matched_categories:
        techniques = bank.get(cat, [])
        if techniques:
            selected.extend(random.sample(techniques, min(2, len(techniques))))

    # Add style-specific guidance
    if style:
        selected.append(f"TARGET STYLE: {style}. Every edit should move the prose closer to this voice.")

    return selected


def build_craft_prompt(genre: str, issues: list[str], style: str = "") -> str:
    """Build a craft-aware prompt section for LLM analysis."""
    techniques = get_relevant_techniques(genre, issues, style)
    if not techniques:
        return ""
    return (
        "CRAFT REFERENCE — apply these techniques where relevant:\n"
        + "\n".join(f"• {t}" for t in techniques)
    )
