FROM us-central1-docker.pkg.dev/wandb-production/chainguard-pull-through/coreweave/chainguard-base:latest AS builder
LABEL maintainer='Weights & Biases <support@wandb.com>'

ARG TARGETARCH

RUN apk add --no-cache python3 git py3-pip gcc python3-dev curl

ARG GO_VERSION=1.26.1
RUN if [ "$TARGETARCH" = "amd64" ]; then \
    curl -L https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz | tar -C /usr/local -xzf -; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
    curl -L https://go.dev/dl/go${GO_VERSION}.linux-arm64.tar.gz | tar -C /usr/local -xzf -; \
    else \
    echo "Unsupported architecture: $TARGETARCH" && exit 1; \
    fi
ENV PATH="/usr/local/go/bin:${PATH}"
ENV WANDB_BUILD_SKIP_GPU_STATS=true
ENV GOTOOLCHAIN=local

# Rust/cargo required to build vendored orjson when installing wandb from source
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && . "$HOME/.cargo/env"
ENV PATH="/root/.cargo/bin:${PATH}"

ARG REF="main"
# PYTHONWARNINGS=ignore suppresses RequestsDependencyWarning during install and at runtime
ENV PYTHONWARNINGS=ignore
RUN pip3 install --upgrade pip \
    && pip3 uninstall -y setuptools \
    && pip3 install --no-cache-dir "wandb[launch] @ git+https://github.com/wandb/wandb.git@$REF"

# --- Final image: no Go toolchain, no build tools ---
FROM us-central1-docker.pkg.dev/wandb-production/chainguard-pull-through/coreweave/chainguard-base:latest
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Suppress RequestsDependencyWarning (pip-resolved urllib3/charset_normalizer often trigger it)
ENV PYTHONWARNINGS=ignore

RUN apk add --no-cache python3 git py3-pip

COPY --from=builder /usr/lib/python3.13/site-packages/ /usr/lib/python3.13/site-packages/

# Copy pip-installed wandb/wb console scripts
RUN mkdir -p /usr/local/bin
COPY --from=builder /usr/bin/wandb /usr/bin/wb /usr/local/bin/

# Set up user
RUN adduser -D -s /bin/sh -u 1000 -G root launch_agent

ENV HOME=/home/launch_agent

USER launch_agent
WORKDIR /home/launch_agent

ARG REF="main"
ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
