# hermes-web-tools

A Hermes Agent general plugin that replaces the built-in `web_search` and
`web_extract` tools with a multi-provider, category-routed suite, and adds
specialized search tools that the model can pick based on query intent.

## Tools

| Tool | Purpose | Providers |
| --- | --- | --- |
| `web_search` | General web search (overrides built-in) | Tavily + Exa(auto) |
| `web_search_realtime` | News / trending / X-Twitter | Grok + Exa(news) |
| `web_search_research` | Papers / deep research | Exa(research, deep) + Tavily(advanced) |
| `web_search_code` | Code context from GitHub / docs / SO | Exa `/context` |
| `web_search_entities` | People / companies / financial reports | Exa + Tavily |
| `web_answer` | Grounded answer with citations | Exa `/answer` |
| `web_extract` | Extract content from URLs (overrides built-in) | MinerU → Firecrawl → Tavily |

Each multi-provider tool runs its backends in parallel, skips a backend that
fails, and merges/dedups results. There is no extra fallback chain — when a
specialized tool returns too little, the model is expected to try another tool.

## Install

From GitHub:

```bash
hermes plugins install https://github.com/niyoh120/hermes-web-tools
```

For development:

```bash
git clone https://github.com/niyoh120/hermes-web-tools.git
cd hermes-web-tools
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Enable in Hermes with `hermes plugins` after installation.

## Configuration

Environment variables (all optional — tools self-gate via `check_fn`):

```
EXA_API_KEY=...
EXA_BASE_URL=https://api.exa.ai
TAVILY_API_KEY=...
TAVILY_BASE_URL=https://api.tavily.com
FIRECRAWL_API_KEY=...
FIRECRAWL_BASE_URL=https://api.firecrawl.dev
GROK_API_URL=http://localhost:8000
GROK_API_KEY=...
GROK_MODEL=grok-4.20-fast
MINERU_API_TOKEN=...
MINERU_BASE_URL=https://mineru.net
MINERU_MODEL_VERSION=vlm
MINERU_AGENT_FALLBACK_ENABLED=false   # token-free MinerU fallback (privacy: sends doc URL to third party)
HERMES_WEB_TOOLS_SEARCH_TIMEOUT=15
HERMES_WEB_TOOLS_EXTRACT_TIMEOUT=120
HERMES_WEB_TOOLS_HEAD_TIMEOUT=3
HERMES_WEB_TOOLS_MAX_URLS=10
HERMES_WEB_TOOLS_MAX_CONTENT_CHARS=50000
HERMES_WEB_TOOLS_MAX_TOTAL_CHARS=200000
```
