FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml README.md LICENSE gaps.default.json config.example.yaml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[postgres]"

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "service_scout", "budget"]
