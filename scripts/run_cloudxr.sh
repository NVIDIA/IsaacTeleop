#!/bin/bash

set -e

# Make sure to run this script from the root of the repository.
GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT" || exit 1

export CXR_HOST_VOLUME_PATH=$HOME/.cloudxr
export CXR_UID=$(id -u)
export CXR_GID=$(id -g)

echo "CXR_UID: $CXR_UID"
echo "CXR_GID: $CXR_GID"
echo "CXR_HOST_VOLUME_PATH: $CXR_HOST_VOLUME_PATH"

# Make sure the host volume path exists
mkdir -p $CXR_HOST_VOLUME_PATH

# Run the docker compose file
docker compose -f deps/cloudxr/docker-compose.yaml up