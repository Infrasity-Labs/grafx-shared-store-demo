# Linux run of the demo. Physical backup and logical export need Linux or Windows.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# The store lives inside the container (local disk). Only the JSON outputs go to /out.
CMD ["python", "run_demo.py", "--workdir", "/work", "--state-dir", "/out"]
