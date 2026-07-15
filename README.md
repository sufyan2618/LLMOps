# LLMOps — local LLM API with observability and CI quality gates

```text
.
├── backend/          # FastAPI app, Dockerfile, tests, evaluation
├── infra/            # kind, k8s, helm, prometheus/loki/otel, compose, scripts
├── models/           # GGUF weights (volume mount; not in git)
├── docs/             # Deploy guide
└── .github/          # CI/CD (Docker Hub; kind deploy on VPS)
```

Quick start:

```bash
# local stack
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build

# kind on VPS
./infra/scripts/deploy-kind.sh
```

See [docs/DEPLOY.md](docs/DEPLOY.md).
