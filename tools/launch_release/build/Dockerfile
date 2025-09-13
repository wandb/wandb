FROM python:3.11-slim-bookworm AS builder

ARG TARGETARCH

RUN apt-get update && apt-get install -y \
    git gcc python3-dev curl
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        curl -L https://go.dev/dl/go1.25.1.linux-amd64.tar.gz | tar -C /usr/local -xzf -; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        curl -L https://go.dev/dl/go1.25.1.linux-arm64.tar.gz | tar -C /usr/local -xzf -; \
    else \
        echo "Unsupported architecture: $TARGETARCH" && exit 1; \
    fi
ENV PATH="/usr/local/go/bin:${PATH}"
ENV WANDB_BUILD_SKIP_GPU_STATS=true

ARG REF="main"
RUN pip install --upgrade pip \
    && pip uninstall -y setuptools \
    && pip install --no-cache-dir git+https://github.com/wandb/wandb.git@$REF #egg=wandb[launch]

RUN mkdir -p /home/launch_agent \
    && chown -R 1000:0 /home/launch_agent

FROM us-central1-docker.pkg.dev/wandb-production/chainguard-pull-through/coreweave/python:3.11
LABEL maintainer='Weights & Biases <support@wandb.com>'

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/wandb* /usr/bin/

# Copy home directory with proper ownership
COPY --from=builder --chown=1000:0 /home/launch_agent /home/launch_agent

ENV HOME=/home/launch_agent

USER 1000:0
WORKDIR /home/launch_agent

ARG REF="main"
ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["/usr/bin/python3", "-m", "wandb", "launch-agent"]
