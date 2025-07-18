FROM python:3.11-slim-bookworm
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Install dependencies
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git gcc python3-dev curl --no-install-recommends \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

# Download and install Go bootstrap
# Go 1.24 ships with a package containing a critical security vulnerability.
# We will use a bootstrap version of Go to build a patched version.
COPY --from=golang:1.24-alpine /usr/local/go/ /usr/local/go-bootstrap
ENV PATH="/usr/local/go/bin:${PATH}"

# Set up Go environment for bootstrap
ENV GOPATH=/go
ENV PATH=$PATH:/usr/local/go-bootstrap/bin:$GOPATH/bin
# Prevents go from downloading potentially vulnerable packages
ENV GOTOOLCHAIN=local

# Clone Go source and build with updated dependencies
# remove bootstrap version of go
RUN git clone https://go.googlesource.com/go /usr/local/go-source && \
    cd /usr/local/go-source && \
    git checkout go1.24.4 && \
    # Update dependencies in the Go source
    cd /usr/local/go-source/src/crypto/internal/fips140/sha3/_asm && \
    go mod edit -require=golang.org/x/crypto@v0.38.0 && \
    go mod tidy && \
    cd /usr/local/go-source/src && \
    go mod edit -require=golang.org/x/crypto@v0.38.0 && \
    go mod edit -require=golang.org/x/net@v0.40.0 && \
    go mod tidy && \
    go mod download && \
    ./make.bash && \
    cd / && \
    mv /usr/local/go-source /usr/local/go && \
    rm -rf /usr/local/go-bootstrap

# Set up final Go environment
ENV PATH=$PATH:/usr/local/go/bin:$GOPATH/bin

# Install Rust minimally and build wandb
ARG REF="main"
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --component cargo && \
    export PATH="/root/.cargo/bin:${PATH}" && \
    pip install --upgrade pip && \
    pip uninstall -y setuptools && \
    pip install --no-cache-dir git+https://github.com/wandb/wandb.git@$REF#egg=wandb[launch] && \
    rm -rf /root/.cargo /root/.rustup && \
    apt-get remove -y curl && \
    apt-get -qy autoremove && \
    apt-get clean && rm -r /var/lib/apt/lists/*

# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
