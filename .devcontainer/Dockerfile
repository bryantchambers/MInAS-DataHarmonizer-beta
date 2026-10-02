FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git-lfs bzip2 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
ARG MINIFORGE_VERSION=25.3.1-0
RUN curl -fsSL "https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/Miniforge3-${MINIFORGE_VERSION}-Linux-x86_64.sh" -o /tmp/miniforge.sh \
    && echo '376b160ed8130820db0ab0f3826ac1fc85923647f75c1b8231166e3d559ab768  /tmp/miniforge.sh' | sha256sum -c - \
    && bash /tmp/miniforge.sh -b -p /opt/miniforge \
    && rm /tmp/miniforge.sh \
    && chown -R vscode:vscode /opt/miniforge
ENV PATH="/opt/miniforge/bin:${PATH}"
