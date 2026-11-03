FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# Yarn is unused; its obsolete upstream apt key otherwise blocks feature installation.
RUN rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.sources
