# Deploy on cloud-ai (oci-n8n)

1. Clone this repo on the host (e.g. `/home/ubuntu/service-scout`).
2. Create Postgres DB + role (same instance as standby is fine):

```sql
CREATE DATABASE service_scout;
CREATE USER scout WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE service_scout TO scout;
```

3. Copy `deploy/systemd/*.service` and `*.timer` to `/etc/systemd/system/`, adjust paths/env.
4. Or use Compose snippet in [deploy/docker-compose.scout.yml](../deploy/docker-compose.scout.yml) merged into oci-n8n stack.
5. Optional n8n: Cron → Execute Command / SSH → `python -m service_scout run`.

Env file example (`/home/ubuntu/stack/secrets/scout.env`):

```
TAVILY_API_KEY=
OLLAMA_BASE_URL=
OLLAMA_MODEL=
NOTION_TOKEN=
SCOUT_DATABASE_URL=postgresql+psycopg://scout:...@portfolio-standby-db:5432/service_scout
```
