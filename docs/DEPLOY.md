# LLMOps — complete runbook

Accounts used in this project:
- **GitHub:** `sufyan2618`
- **Docker Hub:** `sufyanliaqat` → image `sufyanliaqat/llmops-chat`

```text
.
├── backend/     FastAPI app, Dockerfile, tests, evaluation
├── infra/       kind, k8s, helm, observability, compose, scripts
├── models/      GGUF weights (not committed; mounted as volume)
├── docs/        this guide
└── .github/     CI/CD
```

---

# Part A — Run locally

## A1. Prerequisites

- Docker + Docker Compose
- ~6+ GB free RAM (for Qwen3-4B Q4)
- Model file in `models/`

Your file is currently:

```text
models/Qwen3-4B-Q4_K_M.gguf
```

Create the name the app expects:

```bash
cd /path/to/LlmOps
ln -sfn Qwen3-4B-Q4_K_M.gguf models/qwen3-4b-q4_k_m.gguf
ls -lh models/
```

## A2. Env file

```bash
cp .env.example .env
```

Edit `.env` and set Langfuse keys (or disable for offline):

```bash
# Option 1 — with Langfuse Cloud
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_ENABLED=true

# Option 2 — no Langfuse yet
LANGFUSE_ENABLED=false
```

Get Langfuse keys: sign up at https://cloud.langfuse.com → open a project → **Settings → API Keys**.

## A3. Start everything (API + Prometheus + Loki + OTel + Grafana)

```bash
docker compose -f infra/docker-compose.yml up --build
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Health | http://localhost:8000/health |
| Metrics | http://localhost:8000/metrics |
| Grafana | http://localhost:3000 (admin / admin) |
| Prometheus | http://localhost:9090 |
| Loki | http://localhost:3100 |

## A4. Try the API

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Say hello in one word."}'
```

## A5. Run tests (no model needed)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# unit tests stub llama-cpp; or use CI-style stub
pytest -q
```

## A6. Run evaluation locally (against local API)

```bash
# API already running on :8000
cd backend
export EVAL_API_BASE_URL=http://localhost:8000
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_BASE_URL=https://cloud.langfuse.com
python evaluation/run_eval.py
```

Fails if avg accuracy &lt; 0.9 or p95 latency &gt; 2000 ms.

Stop local stack:

```bash
docker compose -f infra/docker-compose.yml down
```

---

# Part B — GitHub secrets (exact list)

Open your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret**.

| Secret name | Required? | Value / how to get |
|---|---|---|
| `DOCKERHUB_USERNAME` | **Yes** (to push images) | `sufyanliaqat` |
| `DOCKERHUB_TOKEN` | **Yes** | Docker Hub → Account Settings → **Personal access tokens** → New Access Token (Read & Write) → paste the token (not your password) |
| `LANGFUSE_PUBLIC_KEY` | For eval scores | Langfuse → Settings → API Keys → `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | For eval scores | Same page → `sk-lf-...` |
| `LANGFUSE_BASE_URL` | For eval (optional) | EU: `https://cloud.langfuse.com` · US: `https://us.cloud.langfuse.com` |
| `PREVIEW_URL` | After VPS is live | `http://YOUR_VPS_IP:30080` |

**Not used anymore:** Argo CD secrets (`ARGOCD_*`) — removed.

### What CI does with them

```text
push to main
  → Lint
  → Tests
  → Docker build
  → Trivy scan
  → Push sufyanliaqat/llmops-chat:<sha> + :latest   (needs Docker Hub secrets)
  → Bump infra/helm/.../values.yaml image tag
  → Smoke test against PREVIEW_URL                 (skipped if unset)
  → Evaluation + Langfuse scores                   (offline tests if no PREVIEW_URL)
```

CI does **not** deploy to the VPS. You deploy with kind on the VPS (Part C). After deploy, set `PREVIEW_URL` so smoke/eval can hit the server.

---

# Part C — Deploy on VPS (kind)

Do these in order.

## C1. On the VPS — install tools

```bash
ssh USER@YOUR_VPS_IP

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# log out and SSH back in

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.27.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
```

VPS sizing: prefer **8 GB RAM** (4B Q4 model + k8s + Prometheus/Loki).

## C2. Copy the model (from your laptop)

On VPS:

```bash
sudo mkdir -p /data/models
sudo chown "$USER:$USER" /data/models
```

On **laptop**:

```bash
rsync -avP ./models/Qwen3-4B-Q4_K_M.gguf \
  USER@YOUR_VPS_IP:/data/models/qwen3-4b-q4_k_m.gguf
```

Verify on VPS:

```bash
ls -lh /data/models/
# must show: qwen3-4b-q4_k_m.gguf
```

## C3. Clone the repo on VPS

```bash
git clone https://github.com/sufyan2618/LlmOps.git
cd LlmOps
```

(If the repo is private, use SSH or a PAT.)

## C4. Langfuse secret for the cluster

```bash
cp infra/k8s/secret.local.yaml.example infra/k8s/secret.local.yaml
nano infra/k8s/secret.local.yaml
```

Paste real `pk-lf-...` and `sk-lf-...`. File is gitignored.

## C5. Get the Docker image on the VPS

**Option A — CI already pushed** (after you set Docker Hub secrets and pushed to `main`):

```bash
docker login   # sufyanliaqat + token
docker pull sufyanliaqat/llmops-chat:latest
```

**Option B — build and push yourself** (laptop or VPS):

```bash
docker login
docker build -t sufyanliaqat/llmops-chat:latest -f backend/Dockerfile backend/
docker push sufyanliaqat/llmops-chat:latest
```

## C6. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 30080/tcp
sudo ufw enable
sudo ufw status
```

Also allow inbound TCP `80` in the VPS provider firewall (DigitalOcean
Networking → Firewalls). Port `30080` is optional after ingress is working.

## C7. Deploy (kind + API + full observability)

```bash
chmod +x infra/scripts/deploy-kind.sh infra/scripts/smoke_test.sh

# PUBLIC_IP is optional; the script detects it automatically.
# Set GRAFANA_ADMIN_PASSWORD to choose your own password.
PUBLIC_IP=YOUR_VPS_IP \
GRAFANA_ADMIN_PASSWORD='use-a-long-random-password' \
./infra/scripts/deploy-kind.sh
```

The script:

1. Creates/reuses the kind cluster and loads the Docker image.
2. Deploys Prometheus, Loki, OTel Collector, Grafana, and Grafana Alloy.
3. Provisions Grafana's Prometheus/Loki datasources and LLMOps dashboard.
4. Installs ingress-nginx and creates public `nip.io` hostnames.
5. Mounts the GGUF from `/data/models` and deploys the API.
6. Prints the Grafana username/password and final URLs.

## C8. Verify

```bash
kubectl get pods -A
kubectl get ingress -A

curl http://api.YOUR_VPS_IP.nip.io/health

curl -X POST http://api.YOUR_VPS_IP.nip.io/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Say hi in one word."}'
```

From your laptop:

```bash
curl http://api.YOUR_VPS_IP.nip.io/health
```

Set GitHub secret:

```text
PREVIEW_URL = http://api.YOUR_VPS_IP.nip.io
```

## C9. Grafana dashboard (no port-forward)

Open:

```text
http://grafana.YOUR_VPS_IP.nip.io
```

The deploy script prints the generated credentials. To retrieve them later:

```bash
echo "user: $(kubectl -n observability get secret grafana-admin \
  -o jsonpath='{.data.admin-user}' | base64 -d)"
echo "password: $(kubectl -n observability get secret grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 -d)"
```

Grafana is preconfigured with:

- **Prometheus**: request totals/rate and p95 chat latency
- **Loki**: Kubernetes pod logs collected by Grafana Alloy
- **LLMOps Chat** dashboard under the `LLMOps` folder

Prometheus/Loki remain internal `ClusterIP` services; Grafana queries them
inside Kubernetes, so they do not need public ingress.

## C10. Redeploy after a new image

```bash
cd LlmOps
git pull
docker pull sufyanliaqat/llmops-chat:latest
IMAGE=sufyanliaqat/llmops-chat:latest ./infra/scripts/deploy-kind.sh
```

---

# Part D — End-to-end checklist

Local
- [ ] Symlink/rename GGUF → `models/qwen3-4b-q4_k_m.gguf`
- [ ] `.env` with Langfuse (or `LANGFUSE_ENABLED=false`)
- [ ] `docker compose -f infra/docker-compose.yml up --build`
- [ ] `curl localhost:8000/health` works

GitHub
- [ ] Repo pushed to `sufyan2618/LlmOps`
- [ ] Secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- [ ] (Later) Langfuse keys + `PREVIEW_URL`
- [ ] Push to `main` → Actions build/push image

VPS
- [ ] Docker, kubectl, kind installed
- [ ] Model at `/data/models/qwen3-4b-q4_k_m.gguf`
- [ ] `secret.local.yaml` with Langfuse keys
- [ ] `./infra/scripts/deploy-kind.sh`
- [ ] TCP 80 allowed by UFW and the VPS provider firewall
- [ ] `api.<VPS_IP>.nip.io/health` works
- [ ] `grafana.<VPS_IP>.nip.io` opens the provisioned dashboard
- [ ] `PREVIEW_URL` set so CI smoke/eval can run

---

# Debug

```bash
kubectl -n llmops get pods,svc
kubectl -n llmops logs -l app.kubernetes.io/name=llmops-chat -f
kubectl -n llmops describe pod -l app.kubernetes.io/name=llmops-chat
kubectl -n observability get pods
kubectl -n observability logs daemonset/alloy
kubectl -n observability logs deployment/grafana
kubectl get ingress -A

# model visible inside kind node?
docker exec llmops-control-plane ls -lh /data/models
```

If pod is `OOMKilled`, resize VPS RAM or lower limits in `infra/k8s/deployment.yaml`.
