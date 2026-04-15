"""Deep pipeline — multi-LLM generation with cross-review for long/complex tasks."""
import asyncio
from dataclasses import dataclass, field

from .models import LLMProvider, LLMResponse, Tier
from .router import build_plan, classify_task, estimate_tokens
from .backends import execute, SYSTEM_DEFAULT
from . import ratelimit


@dataclass
class PipelineResult:
    """Result of a deep pipeline run."""
    draft_responses: list[LLMResponse] = field(default_factory=list)
    reviews: list[LLMResponse] = field(default_factory=list)
    final: LLMResponse | None = None
    total_cost: float = 0.0
    steps_log: list[str] = field(default_factory=list)


def _pick_n_available(providers: list[LLMProvider], n: int, exclude: set[str] | None = None) -> list[LLMProvider]:
    """Pick up to n distinct available providers, preferring free+cheap, respecting rate limits."""
    exclude = exclude or set()
    candidates = [
        p for p in providers
        if p.available and p.model_id not in exclude
        and ratelimit.remaining(p.model_id, p.daily_limit) != 0
    ]
    # Sort: free first, then by cost (cheapest first), then by remaining quota descending
    candidates.sort(key=lambda p: (
        0 if p.tier == Tier.FREE else 1,
        p.cost_per_1k_input + p.cost_per_1k_output,
        -(ratelimit.remaining(p.model_id, p.daily_limit) or 999999),
    ))
    # Deduplicate by provider to get diversity
    seen_providers = set()
    result = []
    for p in candidates:
        if p.provider not in seen_providers:
            result.append(p)
            seen_providers.add(p.provider)
            if len(result) >= n:
                break
    # If not enough diversity, fill from remaining
    if len(result) < n:
        for p in candidates:
            if p not in result:
                result.append(p)
                if len(result) >= n:
                    break
    return result


def _chunk_text(text: str, max_tokens: int = 12000) -> list[str]:
    """Split text into chunks that fit within token limits."""
    words = text.split()
    chunk_words = int(max_tokens * 0.75)  # rough tokens→words
    if len(words) <= chunk_words:
        return [text]
    chunks = []
    for i in range(0, len(words), chunk_words):
        chunks.append(" ".join(words[i:i + chunk_words]))
    return chunks


async def run_deep(prompt: str, providers: list[LLMProvider],
                   system: str | None = None) -> PipelineResult:
    """
    Deep pipeline:
    1. Fan out the prompt to 2-3 different LLMs in parallel (draft phase)
    2. Send all drafts to a reviewer LLM for cross-review
    3. Send the review + best draft to a synthesizer for the final output
    """
    result = PipelineResult()
    sys_prompt = system or SYSTEM_DEFAULT
    tokens = estimate_tokens(prompt)

    # --- Phase 1: Parallel drafts from diverse models ---
    drafters = _pick_n_available(providers, 3)
    if not drafters:
        result.steps_log.append("No providers available for drafting")
        return result

    result.steps_log.append(f"Phase 1 — Drafting with {len(drafters)} models: "
                            + ", ".join(d.name for d in drafters))

    draft_tasks = [execute(d, prompt, max_tokens=4096, system=sys_prompt) for d in drafters]
    drafts = await asyncio.gather(*draft_tasks)
    result.draft_responses = list(drafts)
    result.total_cost += sum(d.cost for d in drafts)

    # Filter successful drafts
    good_drafts = [d for d in drafts if not d.degraded]
    if not good_drafts:
        result.steps_log.append("All drafts failed")
        result.final = drafts[0]  # return best effort
        return result

    result.steps_log.append(f"Got {len(good_drafts)} successful drafts")

    # --- Phase 2: Cross-review ---
    # Pick a reviewer that wasn't a drafter (for independence)
    drafter_models = {d.model_id for d in drafters}
    reviewers = _pick_n_available(providers, 1, exclude=drafter_models)
    # Fall back to best drafter if no independent reviewer available
    reviewer = reviewers[0] if reviewers else drafters[0]

    review_prompt_parts = ["You are reviewing multiple AI-generated responses to the same prompt. "
                           "Be brutally honest about the quality, accuracy, and completeness of each. "
                           "Identify errors, omissions, contradictions, and rank them.\n\n"
                           f"ORIGINAL PROMPT:\n{prompt}\n"]
    for i, d in enumerate(good_drafts):
        review_prompt_parts.append(f"\n--- RESPONSE {i+1} (from {d.provider_name}) ---\n{d.content}\n")
    review_prompt_parts.append("\nProvide:\n1. Ranking (best to worst) with justification\n"
                               "2. Errors or issues in each response\n"
                               "3. What the ideal response would combine from each")

    review_prompt = "".join(review_prompt_parts)
    result.steps_log.append(f"Phase 2 — Review by {reviewer.name}")

    review_resp = await execute(reviewer, review_prompt, max_tokens=4096,
                                system="You are a brutally honest expert reviewer. "
                                       "Point out every flaw without mercy.")
    result.reviews.append(review_resp)
    result.total_cost += review_resp.cost

    if review_resp.degraded:
        result.steps_log.append("Review failed, returning best draft")
        result.final = good_drafts[0]
        return result

    # --- Phase 3: Final synthesis ---
    # Pick the strongest available model for synthesis
    synth_candidates = _pick_n_available(providers, 1)
    synthesizer = synth_candidates[0] if synth_candidates else drafters[0]

    synth_prompt = (
        f"You are producing the definitive, final response to a user's request. "
        f"You have access to multiple draft responses and an expert review.\n\n"
        f"ORIGINAL PROMPT:\n{prompt}\n\n"
    )
    for i, d in enumerate(good_drafts):
        synth_prompt += f"--- DRAFT {i+1} ({d.provider_name}) ---\n{d.content}\n\n"
    synth_prompt += f"--- EXPERT REVIEW ---\n{review_resp.content}\n\n"
    synth_prompt += (
        "Now produce the best possible response by:\n"
        "- Taking the strongest elements from each draft\n"
        "- Fixing all errors identified in the review\n"
        "- Filling any gaps\n"
        "- Being thorough and complete\n"
        "Do NOT mention the drafts or review process. Just give the final answer."
    )

    result.steps_log.append(f"Phase 3 — Synthesis by {synthesizer.name}")

    final_resp = await execute(synthesizer, synth_prompt, max_tokens=8192, system=sys_prompt)
    result.final = final_resp
    result.total_cost += final_resp.cost

    result.steps_log.append(f"Done — total cost: ${result.total_cost:.6f}")
    return result
