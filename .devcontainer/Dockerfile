FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

USER root

# Git and curl are used by Codex CLI and project tooling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Node.js is required to install and run the Codex CLI.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

# An empty named volume inherits the directory's ownership on first mount.
RUN mkdir -p /home/vscode/.codex \
    && chown -R vscode:vscode /home/vscode/.codex

USER vscode
WORKDIR /workspace
