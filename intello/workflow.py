"""Writing workflow engine — manages the step-by-step creation of a book."""
import json
import time
from . import literary
from .guardrails import count_words


def get_workflow_state(project_id: str) -> dict:
    """Compute the current workflow state: what's done, what's next, progress."""
    proj = literary.get_project(project_id)
    if not proj:
        return {"error": "Project not found"}

    # Find linked documents
    with literary._db() as conn:
        docs = conn.execute("SELECT doc_id, total_words FROM documents WHERE project_id=? ORDER BY created_at",
                            (project_id,)).fetchall()

    current_words = sum(d["total_words"] for d in docs)
    target = proj.get("target_words", 0) or 80000
    word_pct = min(100, int(current_words / target * 100)) if target else 0

    steps = proj.get("steps", [])
    iter_state = proj.get("iteration_state", {})
    completed_steps = iter_state.get("completed_steps", [])
    current_step_idx = len(completed_steps)

    # Determine phase
    has_structure = bool(proj.get("character_arcs")) and bool(proj.get("themes")) and bool(steps)
    structure_rich = len(steps) >= 5 and len(proj.get("character_arcs", [])) >= 2

    if not has_structure:
        phase = "outline"
        next_task = "Build the outline: define characters, themes, and plot structure"
        next_label = "📝 Build Outline"
    elif not structure_rich and word_pct < 30:
        phase = "enrich"
        next_task = "Enrich the structure: add subplots, side characters, world-building details"
        next_label = "🌿 Enrich Structure"
    elif current_step_idx < len(steps):
        phase = "expand"
        step = steps[current_step_idx]
        next_task = f"Write the next section: {step}"
        next_label = f"✍️ Write: {step[:30]}..."
    elif word_pct < 90:
        phase = "expand"
        next_task = "Continue expanding the text to reach target word count"
        next_label = "✍️ Expand Text"
    else:
        phase = "polish"
        next_task = "Polish and refine: tighten prose, fix inconsistencies, improve pacing"
        next_label = "✨ Polish"

    return {
        "project_id": project_id,
        "phase": phase,
        "next_task": next_task,
        "next_label": next_label,
        "current_words": current_words,
        "target_words": target,
        "word_pct": word_pct,
        "steps_total": len(steps),
        "steps_completed": len(completed_steps),
        "current_step_idx": current_step_idx,
        "has_structure": has_structure,
        "structure_rich": structure_rich,
    }


def build_horizontal_prompt(proj: dict, state: dict, doc_text: str, budget_pct: int) -> str:
    """Horizontal mode: expand text, write new sections."""
    brief = literary.get_project_brief_prompt(proj["project_id"])
    target_new_words = max(200, int(proj.get("target_words", 5000) * budget_pct / 100 * 0.1))

    if state["phase"] == "outline":
        return f"""{brief}

The project needs an outline. Based on the brief above, generate:
1. A detailed chapter-by-chapter outline (at least 8 chapters)
2. Character profiles with arcs for each major character
3. Key themes and how they develop
4. The narrative structure (setup, rising action, climax, resolution)

Format as structured text that can be used as a writing guide."""

    if state["phase"] == "expand" and state["current_step_idx"] < state["steps_total"]:
        step = proj["steps"][state["current_step_idx"]]
        last_500 = doc_text[-2000:] if doc_text else "(beginning of the book)"
        return f"""{brief}

CURRENT TEXT ENDS WITH:
{last_500}

NEXT STEP TO WRITE: {step}

Write the next section of the book. This should be approximately {target_new_words} words.
Continue naturally from where the text left off. Stay in the established voice and style.
This section should accomplish: {step}

IMPORTANT: Write the ACTUAL prose. Not a summary. Not an outline. The real text of the book.
Target: {target_new_words} words. Count them."""

    # General expansion
    last_500 = doc_text[-2000:] if doc_text else ""
    return f"""{brief}

CURRENT TEXT ({state['current_words']} / {state['target_words']} words):
...{last_500}

Continue writing the next section. Approximately {target_new_words} words.
Maintain the established voice, advance the plot, and develop characters.
Write the ACTUAL prose, not a summary. Target: {target_new_words} words."""


def build_vertical_prompt(proj: dict, state: dict, doc_text: str, budget_pct: int) -> str:
    """Vertical mode: enrich structure, add depth."""
    brief = literary.get_project_brief_prompt(proj["project_id"])
    genre = proj.get("genre", "fiction")

    if not state["structure_rich"]:
        if genre in ("fiction", "screenplay"):
            return f"""{brief}

The structure needs enrichment. Based on the existing outline and text, propose:
1. 2-3 SUBPLOTS that interweave with the main plot (with specific chapter placements)
2. 2-3 SIDE CHARACTERS that add depth (name, role, how they connect to the protagonist)
3. WORLD-BUILDING details: specific locations, customs, objects that make the setting vivid
4. FORESHADOWING opportunities: plant 3-5 seeds early that pay off later
5. THEMATIC ECHOES: scenes that mirror each other to reinforce themes

For each suggestion, specify WHERE in the existing structure it should go.
Format as a structured enhancement plan."""
        else:
            return f"""{brief}

The structure needs enrichment. Propose:
1. 2-3 TANGENTIAL TOPICS that add depth ("did you know" moments)
2. CASE STUDIES or EXAMPLES that illustrate key points
3. COUNTERARGUMENTS to address and strengthen the main thesis
4. ANALOGIES that make complex ideas accessible
5. CONNECTIONS between chapters that create a sense of building understanding

For each, specify WHERE in the existing structure it should go."""

    # Structure is rich — now enrich specific sections
    steps = proj.get("steps", [])
    step_idx = min(state["current_step_idx"], len(steps) - 1) if steps else 0
    focus = steps[step_idx] if steps else "the current section"

    return f"""{brief}

FOCUS SECTION: {focus}

The overall structure is solid. Now deepen this specific section:
1. Add SENSORY DETAILS that ground the reader in the scene
2. Develop CHARACTER INTERIORITY — what are they thinking, feeling, remembering?
3. Add SUBTEXT to dialogue — what's unsaid matters more than what's said
4. Create MICRO-TENSION within the scene (small conflicts, decisions, revelations)
5. Strengthen TRANSITIONS into and out of this section

Provide specific text additions with exact placement instructions.
Format: INSERT AFTER LINE X: [text] — REASON: [why]"""


def mark_step_complete(project_id: str, step_idx: int):
    """Mark a workflow step as completed."""
    proj = literary.get_project(project_id)
    if not proj:
        return
    state = proj.get("iteration_state", {})
    completed = state.get("completed_steps", [])
    if step_idx not in completed:
        completed.append(step_idx)
    state["completed_steps"] = completed
    state["last_updated"] = time.time()
    literary.update_project(project_id, iteration_state=state)
