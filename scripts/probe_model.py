"""Manual probe of the configured model: tool calls and token usage.

Usage: uv run python scripts/probe_model.py [model-id]
Reads provider, key and base URL from the usual settings (CODEMAP_PROVIDER, OPENAI_API_KEY, ...).
Never prints the key.
"""

import sys

from codemap.agents.model import ChatModel
from codemap.agents.providers import make_model
from codemap.settings import Settings

ADD = {
    "name": "add",
    "description": "Add two integers.",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
}
WEATHER = {
    "name": "get_weather",
    "description": "Get the weather for a city.",
    "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def ask(model: ChatModel, prompt: str, tools: list[dict]) -> None:  # type: ignore[type-arg]
    r = model.respond(
        system="Use the tools. Call every tool you need.",
        messages=[{"role": "user", "content": prompt}],
        tools=tools,
        max_tokens=1024,
    )
    uses = [b for b in r.content if b["type"] == "tool_use"]
    print(f"stop={r.stop_reason} tool_calls={[(u['name'], u['input']) for u in uses]}")
    print(f"usage in={r.input_tokens} out={r.output_tokens}")


def main() -> None:
    settings = Settings(model=sys.argv[1]) if len(sys.argv) > 1 else Settings()
    model = make_model(settings)
    print("model:", settings.model_id)
    print("(a) single tool")
    ask(model, "What is 17 + 25?", [ADD])
    print("(b) two tools, parallel possible")
    ask(model, "Add 2 and 3, and also get the weather in Paris and in Rome.", [ADD, WEATHER])


if __name__ == "__main__":
    main()
