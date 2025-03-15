ARG REF="main"

ARG PYTHON_VERSION=3.12
ARG GOLANG_VERSION=1.24
ARG RUST_VERSION=1.85.0

FROM golang:${GOLANG_VERSION}-alpine as golang
FROM rust:${RUST_VERSION}-slim-bullseye as rust
FROM python:${PYTHON_VERSION}-slim-bullseye as builder

# Install Go
COPY --from=golang /usr/local/go/ /usr/local/go/
ENV PATH="/usr/local/go/bin:${PATH}"

# Set Go environment paths
ENV GOPATH /go
ENV PATH $GOPATH/bin:/usr/local/go/bin:$PATH

# Set up Go workspace directories
RUN mkdir -p "$GOPATH/src" "$GOPATH/bin" && chmod -R 777 "$GOPATH"

# Install Rust
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup

ENV CARGO_HOME=/usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup
ENV RUST_VERSION=${RUST_VERSION}
ENV PATH="/usr/local/cargo/bin:${PATH}"

# Install other dependencies
RUN apt-get update && apt-get install -y gcc wget unzip
RUN pip install --upgrade pip build

# Build W&B wheel
WORKDIR /tmp
ARG REF
RUN wget https://github.com/wandb/wandb/archive/${REF}.zip -O wandb.zip && unzip wandb.zip && rm wandb.zip && mv wandb-* wandb

WORKDIR /tmp/wandb
RUN python -m build -w

# Prepare actual image
FROM python:${PYTHON_VERSION}-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

COPY --from=builder /tmp/wandb/dist/*.whl /tmp

RUN pip install --no-cache-dir $(ls /tmp/*.whl)[launch] && rm /tmp/*.whl

# User set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
