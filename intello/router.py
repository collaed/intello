"""Routing engine — classifies prompts and selects the best LLM(s)."""
import re
from .models import LLMProvider, RoutingPlan, TaskType, Tier
from . import ratelimit
from . import memory


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~0.75 words per token for English)."""
    return max(1, int(len(text.split()) / 0.75))


def _has_signal(text: str, signals: list[str]) -> bool:
    """Check if any signal matches as a whole word (or literal like ```)."""
    for s in signals:
        if not s.isalpha():  # literal patterns like ```
            if s in text:
                return True
        elif re.search(rf'\b{re.escape(s)}\b', text):
            return True
    return False


def classify_task(prompt: str) -> TaskType:
    """Heuristic task classification."""
    p = prompt.lower()
    code_signals = ["code", "function", "class", "bug", "implement", "refactor",
                    "python", "javascript", "typescript", "rust", "java", "sql",
                    "api", "debug", "compile", "regex", "algorithm", "```"]
    math_signals = ["math", "equation", "calcul", "integral", "derivative",
                    "proof", "theorem", "solve", "statistic"]
    creative_signals = ["story", "poem", "write me", "creative", "fiction",
                        "blog", "essay", "narrative", "imagine"]
    analysis_signals = ["analyze", "compare", "summarize", "explain", "review",
                        "evaluate", "assess", "research", "report"]
    vision_signals = ["image", "picture", "photo", "screenshot", "diagram"]

    for signals, task in [
        (code_signals, TaskType.CODE),
        (math_signals, TaskType.MATH),
        (vision_signals, TaskType.VISION),
        (creative_signals, TaskType.CREATIVE),
        (analysis_signals, TaskType.ANALYSIS),
    ]:
        if _has_signal(p, signals):
            return task

    tokens = estimate_tokens(prompt)
    if tokens > 3000:
        return TaskType.LONG_CONTEXT
    return TaskType.GENERAL


def _score(provider: LLMProvider, task: TaskType, tokens: int,
           interactive: bool = True) -> float:
    """Score a provider for a given task (higher = better).
    interactive=False means background/batch work — prefer Cloudflare, save Groq."""
    score = 0.0

    # Task-strength match
    if task in provider.strengths:
        score += 50

    # Free tier bonus
    if provider.tier == Tier.FREE:
        score += 30

    # Context window — HARD EXCLUDE if tokens don't fit
    if tokens >= provider.context_window:
        return -9999
    score += 20

    # Penalize cost
    est_cost = (tokens / 1000) * provider.cost_per_1k_input + (tokens / 1000) * provider.cost_per_1k_output
    score -= est_cost * 100

    # --- Interactive vs Background routing ---
    if interactive:
        # Interactive: reward speed (Groq), penalize slow (Cloudflare)
        if provider.provider == "groq":
            score += 25  # fastest inference
        elif provider.provider == "cloudflare":
            score -= 15  # cold starts, slower
    else:
        # Background: reward Cloudflare (huge quota), penalize Groq (save for interactive)
        if provider.provider == "cloudflare":
            score += 30  # 10K/day per model, use it
        elif provider.provider == "groq":
            score -= 20  # save for interactive

    # --- Task-specific provider preferences ---
    # Vision: only Gemini
    if task == TaskType.VISION and provider.provider != "google":
        score -= 100

    # Long context: Gemini (1M) >> Cohere (128K) >> others
    if task == TaskType.LONG_CONTEXT:
        if provider.provider == "google":
            score += 30
        elif provider.provider == "cohere":
            score += 15
        elif provider.provider == "cloudflare":
            score -= 50  # 4-8K context, useless for long

    # Code: DeepSeek V3 for generation, R1 for debugging
    if task == TaskType.CODE:
        if "deepseek-chat" in provider.model_id:
            score += 15  # V3 for generation
        elif "qwen2.5-coder" in provider.model_id:
            score += 10
        elif "deepseek-r1" in provider.model_id:
            score += 8   # R1 for reasoning about code

    # Math: DeepSeek + Gemini Pro
    if task == TaskType.MATH:
        if "deepseek" in provider.model_id:
            score += 15
        elif "gemini-2.5" in provider.model_id:
            score += 12

    # Analysis/RAG: Cohere excels at grounding
    if task == TaskType.ANALYSIS:
        if provider.provider == "cohere":
            score += 20
        elif "gemini-2.5" in provider.model_id:
            score += 10

    # --- Cloudflare context window guard ---
    if provider.provider == "cloudflare" and tokens > 6000:
        score -= 200  # CF models often limited to 4-8K

    # Rate limit awareness
    rem = ratelimit.remaining(provider.model_id, provider.daily_limit)
    if rem == 0:
        score -= 1000
    elif rem != -1:
        pct_left = rem / provider.daily_limit
        if pct_left < 0.1:
            score -= 40
        elif pct_left < 0.3:
            score -= 15

    # Cross-session learning bonus/penalty
    score += memory.get_score_bonus(provider.model_id, task.value)

    return score


def build_plan(prompt: str, providers: list[LLMProvider], prefer_free: bool = True,
               interactive: bool = True) -> RoutingPlan:
    """Build a routing plan for the given prompt.
    interactive=False for background tasks (prefers Cloudflare, saves Groq)."""
    task = classify_task(prompt)
    tokens = estimate_tokens(prompt)

    available = [p for p in providers if p.available]
    unavailable_keys = list({p.env_key for p in providers if not p.available and p.env_key})

    free_available = [p for p in available if p.tier == Tier.FREE]
    paid_available = [p for p in available if p.tier == Tier.PAID]

    # Score and rank
    candidates = free_available if (prefer_free and free_available) else available
    ranked = sorted(candidates, key=lambda p: _score(p, task, tokens, interactive), reverse=True)

    primary = ranked[0] if ranked else None
    fallbacks = ranked[1:4] if len(ranked) > 1 else []

    # If no free options, check paid
    degraded = False
    if not primary and paid_available:
        ranked_paid = sorted(paid_available, key=lambda p: _score(p, task, tokens, interactive), reverse=True)
        primary = ranked_paid[0]
        fallbacks = ranked_paid[1:3]
    elif not primary:
        degraded = True

    # Cost estimation
    est_cost = 0.0
    if primary:
        est_output_tokens = max(tokens, 500)
        est_cost = ((tokens / 1000) * primary.cost_per_1k_input +
                    (est_output_tokens / 1000) * primary.cost_per_1k_output)

    # Build reasoning
    reasoning_parts = [f"Task classified as: {task.value}"]
    reasoning_parts.append(f"Estimated input tokens: ~{tokens}")
    reasoning_parts.append(f"Available providers: {len(available)} ({len(free_available)} free, {len(paid_available)} paid)")
    if primary:
        reasoning_parts.append(f"Selected: {primary.name} (score: {_score(primary, task, tokens, interactive):.1f})")
        rem = ratelimit.remaining(primary.model_id, primary.daily_limit)
        if rem != -1:
            reasoning_parts.append(f"Quota: {rem}/{primary.daily_limit} requests remaining today")
        if primary.tier == Tier.PAID:
            reasoning_parts.append(f"⚠ Using paid model — estimated cost: ${est_cost:.6f}")
    if degraded:
        reasoning_parts.append("⚠ No providers available — degraded mode")
    if unavailable_keys:
        reasoning_parts.append(f"Missing keys: {', '.join(sorted(unavailable_keys))}")

    # Also suggest paid alternatives with cost
    paid_suggestions = []
    for p in providers:
        if p.tier == Tier.PAID and task in p.strengths:
            c = ((tokens / 1000) * p.cost_per_1k_input +
                 (max(tokens, 500) / 1000) * p.cost_per_1k_output)
            paid_suggestions.append(f"  💰 {p.name}: ~${c:.6f} (needs {p.env_key})")
    if paid_suggestions:
        reasoning_parts.append("Paid alternatives:\n" + "\n".join(paid_suggestions))

    return RoutingPlan(
        prompt=prompt,
        task_type=task,
        estimated_tokens=tokens,
        primary=primary,
        fallbacks=fallbacks,
        degraded=degraded,
        missing_keys=unavailable_keys,
        estimated_cost=est_cost,
        reasoning="\n".join(reasoning_parts),
    )
