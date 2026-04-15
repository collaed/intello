"""Debate mode — models argue, challenge, and stress-test each other's answers."""
import asyncio
from dataclasses import dataclass, field

from .models import LLMProvider, LLMResponse, Tier
from .backends import execute
from .pipeline import _pick_n_available
from . import ratelimit


@dataclass
class DebateResult:
    positions: list[dict] = field(default_factory=list)
    challenges: list[dict] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    total_cost: float = 0.0
    log: list[str] = field(default_factory=list)


async def run_debate(prompt: str, providers: list[LLMProvider],
                     system: str | None = None) -> DebateResult:
    """
    Debate mode:
    1. Get initial positions from 3 diverse models
    2. Each model challenges the others' positions
    3. A judge synthesizes the verdict with dissenting opinions
    """
    result = DebateResult()

    # Phase 1: Initial positions
    debaters = _pick_n_available(providers, 3)
    if len(debaters) < 2:
        result.log.append("Not enough models for debate")
        return result

    result.log.append(f"Phase 1 — Positions from: {', '.join(d.name for d in debaters)}")

    position_tasks = [
        execute(d, prompt, max_tokens=2048,
                system="You are a domain expert. Give your definitive position. Be specific and commit to a clear stance. No hedging.")
        for d in debaters
    ]
    positions = await asyncio.gather(*position_tasks)

    for d, p in zip(debaters, positions):
        result.positions.append({
            "model": d.name, "model_id": d.model_id,
            "content": p.content, "cost": p.cost, "degraded": p.degraded,
        })
        result.total_cost += p.cost

    good = [(d, p) for d, p in zip(debaters, positions) if not p.degraded]
    if len(good) < 2:
        result.log.append("Not enough successful positions")
        return result

    # Phase 2: Cross-challenges
    result.log.append("Phase 2 — Cross-challenges")

    challenge_tasks = []
    for i, (challenger_prov, _) in enumerate(good):
        others_text = "\n\n".join(
            f"[{good[j][0].name}]: {good[j][1].content}"
            for j in range(len(good)) if j != i
        )
        challenge_prompt = (
            f"Original question: {prompt}\n\n"
            f"Other experts said:\n{others_text}\n\n"
            f"Your job: Find flaws, errors, weak reasoning, or missing nuance in their positions. "
            f"Be ruthless. Point out specific mistakes. If they're right, say so — but find at least one weakness."
        )
        challenge_tasks.append(
            execute(challenger_prov, challenge_prompt, max_tokens=1500,
                    system="You are a ruthless critic and fact-checker. Tear apart weak arguments.")
        )

    challenges = await asyncio.gather(*challenge_tasks)
    for (prov, _), ch in zip(good, challenges):
        result.challenges.append({
            "challenger": prov.name, "content": ch.content,
            "cost": ch.cost, "degraded": ch.degraded,
        })
        result.total_cost += ch.cost

    # Phase 3: Verdict by independent judge
    judge_candidates = _pick_n_available(providers, 1,
                                          exclude={d.model_id for d, _ in good})
    judge = judge_candidates[0] if judge_candidates else good[0][0]

    result.log.append(f"Phase 3 — Verdict by {judge.name}")

    verdict_prompt = f"Original question: {prompt}\n\n"
    for pos in result.positions:
        if not pos["degraded"]:
            verdict_prompt += f"[{pos['model']}] Position:\n{pos['content']}\n\n"
    for ch in result.challenges:
        if not ch["degraded"]:
            verdict_prompt += f"[{ch['challenger']}] Challenge:\n{ch['content']}\n\n"
    verdict_prompt += (
        "You are the final judge. Based on all positions and challenges above:\n"
        "1. State the CORRECT answer, incorporating the strongest arguments\n"
        "2. Note where models AGREED (high confidence)\n"
        "3. Note where they DISAGREED and who was right\n"
        "4. Flag any claims that remain UNRESOLVED\n"
        "Be definitive. Don't hedge."
    )

    verdict_resp = await execute(judge, verdict_prompt, max_tokens=4096,
                                  system="You are an impartial judge synthesizing expert debate. Be definitive.")
    result.verdict = {
        "judge": judge.name, "model_id": judge.model_id,
        "content": verdict_resp.content, "cost": verdict_resp.cost,
    }
    result.total_cost += verdict_resp.cost
    result.log.append(f"Done — total cost: ${result.total_cost:.6f}")

    return result
