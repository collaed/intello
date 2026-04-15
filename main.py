#!/usr/bin/env python3
"""AI Router — intelligent multi-LLM prompt dispatcher."""
import asyncio
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown

from intello.models import Tier
from intello.research import get_providers, probe_reference_sites
from intello.keys import discover_keys, validate_keys, add_key
from intello.router import build_plan, classify_task, estimate_tokens
from intello.backends import execute

console = Console()


async def startup():
    """Phase 1: Research + key discovery."""
    console.print(Panel("🔍 [bold]AI Router — Startup[/bold]", style="blue"))

    # Probe reference sites
    with console.status("Probing reference sites for market intelligence..."):
        findings = await probe_reference_sites()
    for url, snippet in findings.items():
        status = "✅" if not snippet.startswith("[probe failed") else "⚠️"
        console.print(f"  {status} {url}")
        if not snippet.startswith("[probe failed"):
            console.print(f"     [dim]{snippet[:200]}...[/dim]")

    # Load providers and discover keys
    providers = get_providers()
    discover_keys(providers)

    with console.status("Validating API keys..."):
        await validate_keys(providers)

    # Display provider table
    table = Table(title="Available LLM Providers")
    table.add_column("Provider", style="cyan")
    table.add_column("Model", style="white")
    table.add_column("Tier", style="green")
    table.add_column("Key", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Cost (1K in/out)")

    for p in providers:
        tier_str = "🆓 FREE" if p.tier == Tier.FREE else "💰 PAID"
        key_str = "✅ found" if p.api_key else f"❌ {p.env_key}"
        status = "[green]ready[/green]" if p.available else "[red]unavailable[/red]"
        cost = "free" if p.cost_per_1k_input == 0 else f"${p.cost_per_1k_input:.4f}/${p.cost_per_1k_output:.4f}"
        table.add_row(p.name, p.model_id, tier_str, key_str, status, cost)

    console.print(table)

    avail = [p for p in providers if p.available]
    console.print(f"\n[bold]{len(avail)}[/bold] providers ready "
                  f"({len([p for p in avail if p.tier == Tier.FREE])} free, "
                  f"{len([p for p in avail if p.tier == Tier.PAID])} paid)")

    return providers


def display_plan(plan):
    """Show the routing plan to the user."""
    console.print(Panel(plan.reasoning, title="📋 Routing Plan", style="cyan"))
    if plan.primary:
        tier = "🆓" if plan.primary.tier == Tier.FREE else "💰"
        console.print(f"  → Primary: [bold]{plan.primary.name}[/bold] {tier}")
        if plan.estimated_cost > 0:
            console.print(f"  → Estimated cost: [yellow]${plan.estimated_cost:.6f}[/yellow]")
    for i, fb in enumerate(plan.fallbacks):
        console.print(f"  → Fallback {i+1}: {fb.name}")
    if plan.degraded:
        console.print("[red bold]  ⚠ DEGRADED MODE — no providers available[/red bold]")


async def handle_prompt(prompt: str, providers: list):
    """Route and execute a prompt."""
    plan = build_plan(prompt, providers)
    display_plan(plan)

    if plan.degraded:
        console.print("\n[red]Cannot process — no available providers.[/red]")
        if plan.missing_keys:
            console.print(f"Supply one of: {', '.join(plan.missing_keys)}")
        return

    # Ask for confirmation if paid
    if plan.primary and plan.primary.tier == Tier.PAID:
        if not Confirm.ask(f"This will use [yellow]{plan.primary.name}[/yellow] "
                           f"(~${plan.estimated_cost:.6f}). Proceed?"):
            console.print("Cancelled.")
            return

    # Execute with fallback chain
    chain = [plan.primary] + plan.fallbacks if plan.primary else plan.fallbacks
    for provider in chain:
        if not provider or not provider.available:
            continue
        with console.status(f"Querying {provider.name}..."):
            result = await execute(provider, prompt)
        if not result.degraded:
            console.print(Panel(
                Markdown(result.content),
                title=f"✅ {result.provider_name} ({result.model_id})",
                subtitle=f"tokens: {result.input_tokens}→{result.output_tokens} | cost: ${result.cost:.6f}",
                style="green",
            ))
            return result
        else:
            console.print(f"[yellow]  ⚠ {provider.name} failed: {result.content}[/yellow]")

    console.print("[red]All providers failed.[/red]")


async def main():
    providers = await startup()

    console.print("\n[bold]Ready![/bold] Enter prompts below. Commands: "
                  "[dim]/key ENV_VAR value[/dim] | [dim]/providers[/dim] | "
                  "[dim]/quit[/dim]\n")

    while True:
        try:
            prompt = Prompt.ask("[bold cyan]prompt[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            break

        if not prompt.strip():
            continue
        if prompt.strip() == "/quit":
            break
        if prompt.strip() == "/providers":
            for p in providers:
                s = "✅" if p.available else "❌"
                console.print(f"  {s} {p.name} ({p.provider}) — {p.env_key}")
            continue
        if prompt.strip().startswith("/key "):
            parts = prompt.strip().split(maxsplit=2)
            if len(parts) == 3:
                add_key(providers, parts[1], parts[2])
                with console.status("Validating..."):
                    await validate_keys(providers)
                console.print(f"[green]Key set for {parts[1]}[/green]")
            else:
                console.print("[red]Usage: /key ENV_VAR_NAME your_key_value[/red]")
            continue

        await handle_prompt(prompt, providers)
        console.print()


if __name__ == "__main__":
    asyncio.run(main())
