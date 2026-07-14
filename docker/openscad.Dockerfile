FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

ARG DEBIAN_FRONTEND=noninteractive
ARG OPENSCAD_VERSION=2021.01-6build4

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        fonts-dejavu-core \
        openscad=${OPENSCAD_VERSION} \
        tini \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 seecad \
    && useradd --uid 10001 --gid seecad --create-home --shell /usr/sbin/nologin seecad \
    && mkdir -p /work /opt/libraries \
    && chown seecad:seecad /work

COPY --chown=root:root vendor/NopSCADlib /opt/libraries/NopSCADlib

ENV HOME=/home/seecad \
    OPENSCADPATH=/opt/libraries \
    QT_QPA_PLATFORM=offscreen

WORKDIR /work
USER 10001:10001

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/xvfb-run", "-a", "/usr/bin/openscad"]
