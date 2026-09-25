#!/bin/sh
set -eu
CODE_VERSION=$(git rev-parse HEAD)
export CODE_VERSION
k3d cluster list incidentdesk >/dev/null 2>&1 || k3d cluster create incidentdesk --image rancher/k3s:v1.34.1-k3s1 --agents 2 --servers-memory 3g --agents-memory 2g --wait
mkdir -p .local
docker compose build api worker demo web
docker build -t incidentdesk-sandbox:0.1.0 sandbox
# Export only the host platform; Docker provenance multi-platform indexes otherwise
# reference unavailable blobs when imported by containerd (observed locally).
docker image save --platform="linux/$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/;s/x86_64/amd64/')" -o .local/cluster-images.tar incidentdesk-api:0.1.0 incidentdesk-worker:0.1.0 incidentdesk-demo:0.1.0 incidentdesk-web:0.1.0 incidentdesk-sandbox:0.1.0
for node in k3d-incidentdesk-server-0 k3d-incidentdesk-agent-0 k3d-incidentdesk-agent-1; do
 docker cp .local/cluster-images.tar "$node":/tmp/incident-images.tar
 docker exec "$node" ctr -n k8s.io images import --platform "linux/$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/;s/x86_64/amd64/')" /tmp/incident-images.tar >/dev/null
done
helm upgrade --install incidentdesk deploy/helm/incidentdesk -n incidentdesk --create-namespace --wait --timeout 180s
kubectl -n incidentdesk exec -i postgres-0 -- psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/002_runtime.sql
kubectl -n incidentdesk exec -i postgres-0 -- psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/003_search.sql
