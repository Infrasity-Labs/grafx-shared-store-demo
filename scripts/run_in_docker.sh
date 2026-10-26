#!/bin/sh
# Run all ten steps in a Linux container and write the outputs to ./demo-state.
set -e
cd "$(dirname "$0")/.."
docker build -q -t grafx-shared-store-demo -f docker/Dockerfile .
mkdir -p demo-state
docker run --rm -v "$PWD/demo-state:/out" grafx-shared-store-demo "$@"
