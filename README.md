# Service Scout

[![ci](https://github.com/maximunited/service-scout/actions/workflows/ci.yml/badge.svg)](https://github.com/maximunited/service-scout/actions/workflows/ci.yml)

Budget-governed **research control plane**: finds web services that could help a target project (first target: [portfolio-advisor](https://github.com/maximunited/portfolio-advisor)), judges them with Ollama, and writes every decision to Notion as **accept**, **needs_research**, or **reject**.

It does **not** integrate code or spend Neon CU. Ops state lives on OCI Postgres (`service_scout` DB) or SQLite.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.yaml config.yaml
# Edit secrets: TAVILY_API_KEY, OLLAMA_*, NOTION_TOKEN — or put in env

python -m service_scout init-db
python -m service_scout budget
python -m service_scout run --lane market_data --dry-run
python -m service_scout digest
```

## Docs

| Doc | Purpose |
| --- | ------- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, Notion outcomes, budgets |
| [docs/DEPLOY.md](docs/DEPLOY.md) | cloud-ai / oci-n8n / systemd |
| [docs/LEGAL.md](docs/LEGAL.md) | Copyright / ToS hygiene |

## Design (short)

- **Governor** enforces monthly Tavily + escalation caps (Cursor/MCP headroom reserved).
- **Pre-Ollama classifier** rejects blogs, denylisted domains (e.g. TIKR, Quant Investing, Damodaran Substack), and UI-only terminals before spending LLM/escalation credits.
- **Accept requires ingest evidence** — public REST/GraphQL, free API key limits, or scrapable public JSON — not a free web-terminal account or an FCF essay.
- **Pydantic `AgentVerdict`** gate — invalid JSON never spends tools; retry at lower temperature; else `reject` + `invalid_agent_output`.
- Incomplete research with API signal → Notion **Backlog / Raw** (`needs_research`); content-only → **Rejected**.
- **`service_aliases`** dedupe by domain before Notion.
- Gap registry: HTTP artifact → cache → `gaps.default.json`.
- Multi-target via `targets[]` in config (PA first).
- Optional **reviewer** second pass: set `autotune.reviewer_enabled: true` (rules-only; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## License

MIT. See [LICENSE](LICENSE) and [docs/LEGAL.md](docs/LEGAL.md).
