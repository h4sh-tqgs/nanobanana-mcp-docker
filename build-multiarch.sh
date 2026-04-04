#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="hasshi7965/nanobanana-mcp"
TAG="${1:-latest}"
PLATFORMS="linux/amd64,linux/arm64"
BUILDER_NAME="multiarch"

if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER_NAME" --use
else
  docker buildx use "$BUILDER_NAME"
fi

docker buildx inspect --bootstrap >/dev/null

echo "Building and pushing ${IMAGE_NAME}:${TAG} for ${PLATFORMS}"
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${IMAGE_NAME}:${TAG}" \
  --push \
  .

echo "Inspecting manifest for ${IMAGE_NAME}:${TAG}"
docker buildx imagetools inspect "${IMAGE_NAME}:${TAG}"