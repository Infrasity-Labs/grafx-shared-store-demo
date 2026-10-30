#!/bin/sh
# Run all ten steps in a Linux container. Outputs go to ./runs/<run id>/, never to demo-state/.
#   ./scripts/run_in_docker.sh                 all ten steps
#   ./scripts/run_in_docker.sh --steps 9       any run_demo.py argument
# The scenarios (python run_scenarios.py all) need no Linux and run on the host.
set -e
cd "$(dirname "$0")/.."
SHA="$(git rev-parse HEAD 2>/dev/null || true)"
DIRTY=0
if [ -n "$SHA" ] && [ -n "$(git status --porcelain)" ]; then DIRTY=1; fi
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%.7s' "${SHA:-0000000}")"
[ "$DIRTY" = 1 ] && RUN_ID="$RUN_ID-dirty"
docker build -q -t grafx-shared-store-demo -f docker/Dockerfile \
  --build-arg "DEMO_COMMIT_SHA=$SHA" --build-arg "DEMO_GIT_DIRTY=$DIRTY" .
mkdir -p runs
docker run --rm -v "$PWD/runs:/out" grafx-shared-store-demo \
  --state-dir "/out/$RUN_ID" --run-id "$RUN_ID" --label docker-linux "$@"
echo "Outputs: runs/$RUN_ID"
