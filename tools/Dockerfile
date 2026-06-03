# meshsa base node container
# Build: docker build -f tools/Dockerfile -t meshsa-base:latest .
# Run:   docker run --rm --device=/dev/ttyUSB0 \
#          -e MESHSA_FTS_HOST=host.docker.internal \
#          meshsa-base:latest

FROM python:3.12-slim AS builder

WORKDIR /build
COPY packages/meshsa /build/meshsa

RUN pip install --no-cache-dir --upgrade pip build \
 && cd /build/meshsa \
 && python -m build --wheel --outdir /build/dist


FROM python:3.12-slim AS runtime

ARG APP_USER=meshsa
ARG APP_UID=10001

RUN groupadd -r -g ${APP_UID} ${APP_USER} \
 && useradd -r -u ${APP_UID} -g ${APP_USER} -s /usr/sbin/nologin ${APP_USER} \
 && apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl[meshtastic] \
 && rm /tmp/*.whl

USER ${APP_USER}
WORKDIR /home/${APP_USER}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/usr/bin/tini", "--", "meshsa-base"]
