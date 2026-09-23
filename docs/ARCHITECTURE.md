# Architecture

## Outcomes (Notion)

| Scout verdict | Status | Refinement |
| ------------- | ------ | ---------- |
| `accept` | Backlog | Raw |
| `needs_research` | Backlog | Raw |
| `reject` | Rejected | Raw |

Every path also appends an **AgDR** row in the ops DB.

## Modules

| Module | Role |
| ------ | ---- |
| `config` | YAML + env |
| `governor` | Tavily / escalation budget |
| `gaps` | Fetch + cache gap registry |
| `lanes` | `LaneResult` builders |
| `agent` | Ollama + Pydantic |
| `dedupe` | `service_aliases` |
| `decide` | Notion + digest queue |
| `runner` | Orchestration |
| `digest` | Apprise weekly flush |

## Storage

Prefer `database.url` → Postgres database **`service_scout`** on OCI (not `portfolio_advisor`, not Neon). SQLite via `database.sqlite_path` is the fallback.
