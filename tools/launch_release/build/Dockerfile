FROM python:3.9-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# install wget
# Install Go.
COPY --from=golang:bookworm /usr/local/go/ /usr/local/go/
# Set Go environment paths
ENV GOPATH /go
ENV PATH $GOPATH/bin:/usr/local/go/bin:$PATH

# Set up Go workspace directories
RUN mkdir -p "$GOPATH/src" "$GOPATH/bin" && chmod -R 777 "$GOPATH"

# Install Rust using Rustup
RUN apt-get update && apt-get install -y curl && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
    apt-get remove -y curl && apt-get -qy autoremove && \
    apt-get clean && rm -r /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"


# install git
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git gcc python3-dev \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

# required pip packages
ARG REF="main"
RUN pip install --upgrade pip && \
    pip uninstall -y setuptools && \
    pip install --no-cache-dir git+https://github.com/wandb/wandb.git@$REF#egg=wandb[launch]
# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
