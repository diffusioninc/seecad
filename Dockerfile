FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
ARG OPENSCAD_VERSION=2021.01-6build4

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        fonts-dejavu-core \
        openscad=${OPENSCAD_VERSION} \
        python3.12 \
        python3.12-venv \
        tini \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.26@sha256:9a23023be68b2ed09750ae636228e903a54a05ea56ed03a934d00fe9fbeded4b /uv /uvx /bin/

RUN groupadd --gid 10001 seecad \
    && useradd --uid 10001 --gid seecad --create-home --shell /usr/sbin/nologin seecad \
    && mkdir -p /app /data /opt/libraries /opt/seecad /run/seecad \
    && chown -R seecad:seecad /app /data /run/seecad \
    && chmod 0700 /run/seecad

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY vendor/NopSCADlib /opt/libraries/NopSCADlib
COPY vendor/NopSCADlib.UPSTREAM.json /opt/libraries/NopSCADlib.UPSTREAM.json
COPY Dockerfile /opt/seecad/Dockerfile.build-source
ARG SEECAD_WORKER_BUILD_SEED=compose-v1
RUN SEECAD_WORKER_BUILD_SEED="${SEECAD_WORKER_BUILD_SEED}" \
    PYTHONPATH=/app/src \
    /app/.venv/bin/python - <<'PY'
import os
from pathlib import Path

from seecad.config import derive_worker_build_id

root = Path("/app")
inputs = [
    ("Dockerfile", Path("/opt/seecad/Dockerfile.build-source")),
    ("pyproject.toml", root / "pyproject.toml"),
    ("uv.lock", root / "uv.lock"),
]
inputs.extend(
    (f"src/seecad/{path.name}", path)
    for path in sorted((root / "src/seecad").glob("*.py"))
)
identity = derive_worker_build_id(
    ((name, path.read_bytes()) for name, path in inputs),
    seed=os.environ["SEECAD_WORKER_BUILD_SEED"],
)
target = Path("/opt/seecad/worker-build-id")
target.write_text(identity + "\n", encoding="ascii")
target.chmod(0o444)
PY
RUN uv sync --frozen --no-dev

ENV PATH=/app/.venv/bin:$PATH \
    HOME=/home/seecad \
    OPENSCADPATH=/opt/libraries \
    QT_QPA_PLATFORM=offscreen \
    SEECAD_DATA_DIR=/data \
    SEECAD_NOPSCAD_ROOT=/opt/libraries/NopSCADlib \
    SEECAD_OPENSCAD_MODE=remote \
    PYTHONUNBUFFERED=1

USER 10001:10001
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "seecad.api:app", "--host", "0.0.0.0", "--port", "8000"]
