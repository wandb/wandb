FROM us-central1-docker.pkg.dev/wandb-production/chainguard-pull-through/coreweave/chainguard-base:latest
LABEL maintainer='Weights & Biases <support@wandb.com>'

ARG TARGETARCH

RUN apk add --no-cache python3 git py3-pip gcc python3-dev curl

# Install Go
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        curl -L https://go.dev/dl/go1.25.3.linux-amd64.tar.gz | tar -C /usr/local -xzf -; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        curl -L https://go.dev/dl/go1.25.3.linux-arm64.tar.gz | tar -C /usr/local -xzf -; \
    else \
        echo "Unsupported architecture: $TARGETARCH" && exit 1; \
    fi
ENV PATH="/usr/local/go/bin:${PATH}"
ENV WANDB_BUILD_SKIP_GPU_STATS=true

# Install wandb
ARG REF="main"
RUN pip3 install --upgrade pip \
    && pip3 uninstall -y setuptools \
    && pip3 install --no-cache-dir "wandb[launch] @ git+https://github.com/wandb/wandb.git@$REF"

# Set up user
RUN adduser -D -s /bin/sh -u 1000 -G root launch_agent

ENV HOME=/home/launch_agent

USER launch_agent
WORKDIR /home/launch_agent

ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["/usr/bin/python3", "-m", "wandb", "launch-agent"]
