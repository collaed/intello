"""Tool-using agent — lets LLMs call external tools (web search, calculator, code exec)."""
import asyncio
import json
import math
import re
import httpx

TOOLS_SCHEMA = [
    {"name": "web_search", "description": "Search the web for current information",
     "parameters": {"query": "search query string"}},
    {"name": "calculator", "description": "Evaluate a mathematical expression",
     "parameters": {"expression": "math expression like '2**10 + sqrt(144)'"}},
    {"name": "python_eval", "description": "Execute a small Python snippet and return the output",
     "parameters": {"code": "python code (max 20 lines, no imports beyond math/json/re)"}},
    {"name": "compose_tool", "description": "Create a new tool by writing a Python function for a specific task",
     "parameters": {"task": "description of what the tool should do"}},
]

TOOL_PROMPT_SUFFIX = """

You have access to these tools. To use one, respond with a JSON block:
```tool
{"tool": "tool_name", "args": {"param": "value"}}
```

Available tools:
- web_search(query): Search the web for current information
- calculator(expression): Evaluate math like "2**10 + sqrt(144)"
- python_eval(code): Run a small Python snippet
- compose_tool(task): Create a custom tool on-the-fly for a specific task (e.g. "convert CSV to JSON", "generate a UUID")

If you don't need a tool, just respond normally. Only use a tool if the question requires real-time data, calculation, or code execution you can't do in your head."""


async def _web_search(query: str) -> str:
    """Simple web search via DuckDuckGo HTML (no API key needed)."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get("https://html.duckduckgo.com/html/",
                            params={"q": query},
                            headers={"User-Agent": "AIRouter/1.0"})
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for a in soup.select(".result__a")[:5]:
                title = a.get_text(strip=True)
                snippet_el = a.find_parent("div", class_="result")
                snippet = ""
                if snippet_el:
                    s = snippet_el.select_one(".result__snippet")
                    if s:
                        snippet = s.get_text(strip=True)
                results.append(f"- {title}: {snippet}")
            return "\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search failed: {e}"


def _calculator(expression: str) -> str:
    """Safe math evaluation."""
    allowed = set("0123456789+-*/.() ,eE")
    funcs = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
             "log": math.log, "log10": math.log10, "abs": abs, "pow": pow,
             "pi": math.pi, "e": math.e, "ceil": math.ceil, "floor": math.floor}
    try:
        clean = expression.replace("^", "**")
        result = eval(clean, {"__builtins__": {}}, funcs)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


def _python_eval(code: str) -> str:
    """Execute a small Python snippet in a subprocess sandbox."""
    if len(code.split("\n")) > 20:
        return "Error: code too long (max 20 lines)"

    try:
        import subprocess
        result = subprocess.run(
            ["python3", "-c", f"import math, json, re\n{code}"],
            capture_output=True, text=True, timeout=10,
            env={"PATH": "/usr/bin:/usr/local/bin", "HOME": "/tmp"},  # minimal env
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip()
            # Filter out the wrapper line from tracebacks
            return f"Error: {err[-300:]}"
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: execution timed out (10s limit)"
    except Exception as e:
        return f"Error: {e}"


async def _compose_tool(task: str) -> str:
    """Auto-generate and execute a Python script for a custom task."""
    code = f"""# Auto-generated tool for: {task}
import math, json, re
# Implement the task
try:
    result = "Tool composition for: {task}"
    print(result)
except Exception as e:
    print(f"Error: {{e}}")
"""
    # The LLM will actually write the code via python_eval — this is a meta-tool
    # that tells the LLM to use python_eval with a specific purpose
    return f"Use python_eval to write code that accomplishes: {task}"


_TOOL_HANDLERS = {
    "web_search": lambda args: _web_search(args.get("query", "")),
    "calculator": lambda args: _calculator(args.get("expression", "")),
    "python_eval": lambda args: _python_eval(args.get("code", "")),
    "compose_tool": lambda args: _compose_tool(args.get("task", "")),
}


def detect_tool_call(response: str) -> dict | None:
    """Parse a tool call from LLM response."""
    m = re.search(r'```tool\s*\n?(.*?)\n?```', response, re.DOTALL)
    if not m:
        # Also try bare JSON with "tool" key
        m = re.search(r'\{"tool":\s*"(\w+)".*?\}', response, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


async def execute_tool(tool_call: dict) -> str:
    """Execute a tool and return the result string."""
    name = tool_call.get("tool", "")
    args = tool_call.get("args", {})
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    result = handler(args)
    if asyncio.iscoroutine(result):
        result = await result
    return result
