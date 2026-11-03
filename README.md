# LLM Spend Agent

An MCP server that lets executives ask their own LLM (Claude, Cursor) plain-English questions about LLM spend and usage across Anthropic and OpenAI, such as "Who spent the most this month?" or "Which models cost the most this week?"

**Status:** design and early development. See [DESIGN.md](DESIGN.md) for the problem, requirements, architecture and milestones.

## Development

```bash
uv venv && uv pip install -e . pytest
pytest
```

## License

MIT
