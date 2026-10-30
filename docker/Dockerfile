# Linux run of the demo. Physical backup and logical export need Linux or Windows.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# .git is not in the image. scripts/run_in_docker.sh passes the commit so the run manifest can record it.
ARG DEMO_COMMIT_SHA=
ARG DEMO_GIT_DIRTY=0
ENV DEMO_COMMIT_SHA=${DEMO_COMMIT_SHA} DEMO_GIT_DIRTY=${DEMO_GIT_DIRTY}
# The store lives inside the container (local disk). Only the run folder goes to /out.
# Extra arguments to docker run are passed to run_demo.py (for example --steps 1 2 3).
ENTRYPOINT ["python", "run_demo.py", "--workdir", "/work"]
