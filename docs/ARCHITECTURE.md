# Architecture

## Outcomes (Notion)

| Scout verdict | Status | Refinement |
| ------------- | ------ | ---------- |
| `accept` | Backlog | Raw |
| `needs_research` | Backlog | Raw |
| `reject` | Rejected | Raw |

Every path also appends an **AgDR** row in the ops DB.

## False-positive filters (market_data)

Gap seeds like “free tools to analyze cash flow” used to pull essays and UI terminals; Ollama treated “talks about free FCF” as signal. Hard gates now:

1. **Pre-Ollama classifier** (`classify.py`) — denylist domains (TIKR, Quant Investing, Damodaran Substack), content-only URL/title patterns (blog/substack/academy/guide/primer), UI-only without API mention → auto-`reject` with `not_a_data_source` / `content_only_no_api` / `ui_only_no_api` / `denylist_domain` (skips LLM).
2. **Ingest evidence** — `accept` requires REST/GraphQL/JSON endpoint / free API key / scrapable public JSON signal in free-tier + snippets. Free *web terminal account* is not enough.
3. **Gap seeds** — prefer `free REST API` / `free JSON endpoint` / `public API free tier` wording.
4. **Blog-only `need_more`** → `reject` (`content_only_no_api`), not perpetual Backlog.

## Optional independent reviewer stage

`reviewer.py` is a **gated second pass** (off by default: `autotune.reviewer_enabled`). It is adversarial (“is this actually ingestible?”), rules-first; Ollama stub only if `reviewer_use_ollama`. Differs from **governor** (budget) and **first-pass Ollama** (triage). Enable after measuring false-positive rate; keep Ollama off until a small monthly review budget is defined.

## Modules

| Module | Role |
| ------ | ---- |
| `config` | YAML + env |
| `governor` | Tavily / escalation budget |
| `gaps` | Fetch + cache gap registry |
| `lanes` | `LaneResult` builders |
| `classify` | Pre-Ollama URL / denylist / content-only |
| `agent` | Ollama + Pydantic |
| `reviewer` | Optional second-pass ingestibility gate |
| `dedupe` | `service_aliases` |
| `decide` | Free-first gates + Notion + digest queue |
| `runner` | Orchestration |
| `digest` | Apprise weekly flush |

## Storage

Prefer `database.url` → Postgres database **`service_scout`** on OCI (not `portfolio_advisor`, not Neon). SQLite via `database.sqlite_path` is the fallback.
