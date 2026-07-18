#!/usr/bin/env bash
# Deploy LLMOps to a local kind cluster on the VPS (observability + API).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-llmops}"
IMAGE="${IMAGE:-sufyanliaqat/llmops-chat:latest}"
MODEL_HOST_DIR="${MODEL_HOST_DIR:-/data/models}"
MODEL_FILE="${MODEL_FILE:-qwen3-4b-q4_k_m.gguf}"
PUBLIC_IP="${PUBLIC_IP:-}"
INGRESS_NGINX_MANIFEST="https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml"

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing dependency: $1"; exit 1; }; }
need docker
need kind
need kubectl
need curl

if [[ -z "${PUBLIC_IP}" ]]; then
  PUBLIC_IP="$(curl -fsS https://api.ipify.org)"
fi

echo "==> Ensuring model directory exists: ${MODEL_HOST_DIR}"
sudo mkdir -p "${MODEL_HOST_DIR}"
if [[ ! -f "${MODEL_HOST_DIR}/${MODEL_FILE}" ]]; then
  echo "WARNING: ${MODEL_HOST_DIR}/${MODEL_FILE} not found."
  echo "Copy it from your laptop first, e.g.:"
  echo "  rsync -avP ./models/${MODEL_FILE} user@VPS_IP:${MODEL_HOST_DIR}/"
fi

echo "==> Creating kind cluster (idempotent)"
if ! kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  kind create cluster --name "${CLUSTER_NAME}" --config "${ROOT}/kind/cluster.yaml"
else
  echo "Cluster ${CLUSTER_NAME} already exists"
  kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null
fi

echo "==> Pulling image ${IMAGE} and loading into kind"
docker pull "${IMAGE}"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"

echo "==> Applying namespaces + observability (OTel, Loki, Prometheus)"
kubectl apply -f "${ROOT}/k8s/namespace.yaml"
kubectl apply -f "${ROOT}/k8s/observability.yaml"

echo "==> Creating/reusing Grafana admin credentials"
if kubectl -n observability get secret grafana-admin >/dev/null 2>&1; then
  GRAFANA_ADMIN_USER="$(kubectl -n observability get secret grafana-admin -o jsonpath='{.data.admin-user}' | base64 -d)"
  GRAFANA_ADMIN_PASSWORD="$(kubectl -n observability get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d)"
else
  GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
  GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-$(tr -d '-' < /proc/sys/kernel/random/uuid)}"
  kubectl -n observability create secret generic grafana-admin \
    --from-literal=admin-user="${GRAFANA_ADMIN_USER}" \
    --from-literal=admin-password="${GRAFANA_ADMIN_PASSWORD}"
fi

echo "==> Deploying Grafana dashboards and Alloy pod-log collection"
kubectl apply -f "${ROOT}/k8s/grafana.yaml"
kubectl apply -f "${ROOT}/k8s/alloy.yaml"

echo "==> Applying model PVC + app config"
kubectl apply -f "${ROOT}/k8s/pvc-model.yaml"
kubectl apply -f "${ROOT}/k8s/configmap.yaml"

if [[ -f "${ROOT}/k8s/secret.local.yaml" ]]; then
  echo "==> Applying secret.local.yaml"
  kubectl apply -f "${ROOT}/k8s/secret.local.yaml"
else
  echo "==> Applying placeholder secret (edit infra/k8s/secret.yaml or create secret.local.yaml)"
  kubectl apply -f "${ROOT}/k8s/secret.yaml"
fi

echo "==> Deploying API via kubectl/kind (image=${IMAGE})"
# Patch image on the fly without editing committed YAML permanently
kubectl apply -f "${ROOT}/k8s/deployment.yaml"
kubectl -n llmops set image deployment/llmops-chat api="${IMAGE}"
kubectl apply -f "${ROOT}/k8s/service.yaml"
kubectl apply -f "${ROOT}/k8s/nodeport.yaml" || true

echo "==> Installing ingress-nginx for kind"
kubectl apply -f "${INGRESS_NGINX_MANIFEST}"
kubectl -n ingress-nginx wait \
  --for=condition=Ready pod \
  -l app.kubernetes.io/component=controller \
  --timeout=300s

echo "==> Applying API and Grafana ingress routes"
sed "s/__PUBLIC_IP__/${PUBLIC_IP}/g" "${ROOT}/k8s/ingress.yaml" | kubectl apply -f -

echo "==> Waiting for observability pods"
kubectl -n observability wait --for=condition=available deployment --all --timeout=300s || true
kubectl -n observability rollout status daemonset/alloy --timeout=300s || true

echo "==> Waiting for llmops-chat (model load can take a while)"
kubectl -n llmops rollout status deployment/llmops-chat --timeout=600s || {
  echo "Rollout not ready yet — check: kubectl -n llmops describe pod -l app.kubernetes.io/name=llmops-chat"
  kubectl -n llmops get pods -o wide
  exit 1
}

echo ""
echo "Deployed."
echo "  API:      http://api.${PUBLIC_IP}.nip.io"
echo "  Grafana:  http://grafana.${PUBLIC_IP}.nip.io"
echo "  Grafana user: ${GRAFANA_ADMIN_USER}"
echo "  Grafana password: ${GRAFANA_ADMIN_PASSWORD}"
echo "  Health:  curl http://api.${PUBLIC_IP}.nip.io/health"
echo "  Chat:    curl -X POST http://api.${PUBLIC_IP}.nip.io/chat -H 'Content-Type: application/json' -d '{\"message\":\"hi\"}'"
echo "  Metrics: curl http://127.0.0.1:30080/metrics | head"
echo "  Prometheus/Loki: available as Grafana datasources"
echo "  OTel: kubectl -n observability get svc otel-collector"
echo ""
echo "Ensure VPS firewall/security-group allows TCP 80 (and 443 when TLS is added)."
