FROM python:3.9-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Install Go.
COPY --from=golang:1.23-alpine /usr/local/go/ /usr/local/go/


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

# Install git and build dependencies
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y gcc python3-dev git \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*


# Install required pip packages and `wandb` from GitHub
ARG REF="main"
RUN pip install --upgrade pip && \
    pip uninstall -y setuptools && \
    pip install --no-cache-dir git+https://github.com/wandb/wandb.git@$REF#egg=wandb[launch]

# Remove the existing Go installation
RUN rm -rf /usr/local/go

# Clean cargo cache from /root/.cargo
RUN cargo install cargo-cache && cargo cache -a && cargo uninstall cargo-cache

# User setup
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent


ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
