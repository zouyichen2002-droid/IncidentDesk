#!/bin/sh
set -eu
CODE_VERSION=$(git rev-parse HEAD)
export CODE_VERSION
revision=${1:-0.3.0}
docker compose build api worker demo web > /tmp/incident-revision-build.log 2>&1
for component in api worker demo web; do docker tag "incidentdesk-$component:0.1.0" "incidentdesk-$component:$revision"; done
docker image save --platform="linux/$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/;s/x86_64/amd64/')" -o .local/revision.tar "incidentdesk-api:$revision" "incidentdesk-worker:$revision" "incidentdesk-demo:$revision" "incidentdesk-web:$revision" incidentdesk-sandbox:0.1.0
for node in k3d-incidentdesk-server-0 k3d-incidentdesk-agent-0 k3d-incidentdesk-agent-1; do
 docker cp .local/revision.tar "$node":/tmp/incident-revision.tar
 docker exec "$node" ctr -n k8s.io images import --platform "linux/$(docker info --format '{{.Architecture}}' | sed 's/aarch64/arm64/;s/x86_64/amd64/')" /tmp/incident-revision.tar >/dev/null
done
helm upgrade incidentdesk deploy/helm/incidentdesk -n incidentdesk --set imageTag="$revision" --set workerReplicas=3 --force-conflicts --wait --timeout 180s
