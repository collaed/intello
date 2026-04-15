"""Prompt chaining — decomposes complex prompts into sub-tasks and routes each optimally."""
import asyncio
import json
import re

from .models import LLMProvider, LLMResponse
from .router import classify_task, build_plan
from .backends import execute, SYSTEM_DEFAULT

DECOMPOSE_PROMPT = """Analyze this user request and determine if it needs to be broken into sub-tasks.

If it's a simple, single-step request, respond with:
{"chain": false}

If it's complex and benefits from decomposition, respond with:
{"chain": true, "steps": [
  {"task": "description of step 1", "type": "code|math|analysis|creative|general"},
  {"task": "description of step 2", "type": "..."},
  ...
]}

Rules:
- Max 4 steps
- Each step should be independently answerable
- Later steps can reference "the result of step N"
- Only decompose if it genuinely helps (don't split simple questions)

User request: """


async def analyze_complexity(prompt: str, providers: list[LLMProvider]) -> dict:
    """Use a fast cheap model to decide if prompt needs chaining."""
    plan = build_plan(DECOMPOSE_PROMPT + prompt, providers)
    if not plan.primary:
        return {"chain": False}

    # Pick fastest available (Groq/Cloudflare preferred)
    fast = None
    for p in providers:
        if p.available and p.provider in ("groq", "cloudflare", "mistral"):
            fast = p
            break
    if not fast:
        fast = plan.primary

    result = await execute(fast, DECOMPOSE_PROMPT + prompt, max_tokens=300,
                           system="You are a task decomposition engine. Respond ONLY with valid JSON.")
    if result.degraded:
        return {"chain": False}

    # Parse JSON from response
    try:
        text = result.content.strip()
        # Extract JSON from markdown code blocks if present
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"chain": False}


async def execute_chain(prompt: str, steps: list[dict], providers: list[LLMProvider],
                        system: str | None = None) -> dict:
    """Execute a chain of sub-tasks, passing context between steps."""
    sys_prompt = system or SYSTEM_DEFAULT
    results = []
    context_so_far = f"Original request: {prompt}\n\n"

    for i, step in enumerate(steps):
        step_prompt = (
            f"{context_so_far}"
            f"Now complete this specific step:\n{step['task']}\n\n"
            f"Be thorough and specific. This is step {i+1} of {len(steps)}."
        )

        # Route based on step's task type
        plan = build_plan(step_prompt, providers)
        if not plan.primary:
            results.append({"step": i + 1, "task": step["task"], "error": "No provider available"})
            continue

        t_result = await execute(plan.primary, step_prompt, max_tokens=4096, system=sys_prompt)

        step_result = {
            "step": i + 1,
            "task": step["task"],
            "type": step.get("type", "general"),
            "provider": t_result.provider_name,
            "model": t_result.model_id,
            "content": t_result.content,
            "cost": t_result.cost,
            "degraded": t_result.degraded,
        }
        results.append(step_result)

        # Add to rolling context for next steps
        if not t_result.degraded:
            context_so_far += f"Step {i+1} result ({step['task']}):\n{t_result.content}\n\n"

    # Final synthesis
    synth_prompt = f"Original request: {prompt}\n\nHere are the results of each sub-task:\n\n"
    for r in results:
        if not r.get("degraded") and not r.get("error"):
            synth_prompt += f"Step {r['step']} ({r['task']}):\n{r['content']}\n\n"
    synth_prompt += "Now synthesize all of the above into a single, coherent, complete response to the original request."

    plan = build_plan(synth_prompt, providers)
    if plan.primary:
        final = await execute(plan.primary, synth_prompt, max_tokens=8192, system=sys_prompt)
    else:
        # Fallback: concatenate step results
        final = LLMResponse("chain", "synthesis", "\n\n".join(
            r["content"] for r in results if not r.get("degraded") and not r.get("error")))

    total_cost = sum(r.get("cost", 0) for r in results) + (final.cost if final else 0)

    return {
        "steps": results,
        "final": {
            "provider": final.provider_name,
            "model": final.model_id,
            "content": final.content,
            "cost": total_cost,
        },
    }
