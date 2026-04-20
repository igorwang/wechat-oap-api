#!/usr/bin/env bash
# Build multi-arch image (amd64 + arm64) and push to Docker Hub.
#
# Requires: `docker login` as igorwang, and a buildx builder that supports
# both platforms (QEMU is set up automatically on Docker Desktop).
#
# Usage:
#   scripts/docker-push.sh              # tags :latest and the pyproject version
#   scripts/docker-push.sh v0.2.0       # tags :latest and :v0.2.0
set -euo pipefail

IMAGE="igorwang/wechat-oap-api"
BUILDER="${BUILDX_BUILDER:-mybuilder}"

PYPROJECT_VERSION=$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
VERSION_TAG="${1:-$PYPROJECT_VERSION}"

echo ">> Building ${IMAGE}:latest and ${IMAGE}:${VERSION_TAG} for linux/amd64,linux/arm64"

docker buildx build \
  --builder "$BUILDER" \
  --platform linux/amd64,linux/arm64 \
  --tag "${IMAGE}:latest" \
  --tag "${IMAGE}:${VERSION_TAG}" \
  --push \
  .

echo ">> Pushed: ${IMAGE}:latest, ${IMAGE}:${VERSION_TAG}"
