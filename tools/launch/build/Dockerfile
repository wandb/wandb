# Start with a common base image available for both architectures
FROM python:3.9-slim-bullseye AS base
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Common installations and setup
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git gcc python3-dev \
    apt-transport-https ca-certificates curl gnupg lsb-release \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

# Install Go for AMD64
FROM base AS go-amd64
COPY --from=golang:1.22-alpine /usr/local/go/ /usr/local/go/

# Install Go for ARM64
FROM base AS go-arm64
COPY --from=golang:1.22-alpine /usr/local/go/ /usr/local/go/

# Final stage
FROM base AS final

# Copy Go based on architecture
COPY --from=go-amd64 /usr/local/go/ /usr/local/go/
COPY --from=go-arm64 /usr/local/go/ /usr/local/go/

ENV PATH="/usr/local/go/bin:${PATH}"

# Set Go environment paths
ENV GOPATH /go
ENV PATH $GOPATH/bin:/usr/local/go/bin:$PATH

# Set up Go workspace directories
RUN mkdir -p "$GOPATH/src" "$GOPATH/bin" && chmod -R 777 "$GOPATH"

# Add Docker's official GPG key
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Set up the Docker repository
RUN echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Add Microsoft's official GPG key
RUN curl -sL https://packages.microsoft.com/keys/microsoft.asc | \
    gpg --dearmor | \
    tee /etc/apt/trusted.gpg.d/microsoft.gpg > /dev/null

# Add Azure CLI repository
RUN AZ_REPO=$(lsb_release -cs) && \
    echo "deb [arch=$(dpkg --print-architecture)] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | \
    tee /etc/apt/sources.list.d/azure-cli.list

# Install Docker and Azure CLI
RUN apt-get update && \
    apt-get install -y docker-ce docker-ce-cli containerd.io azure-cli

# required pip packages
ARG REF="main"
RUN pip install --upgrade pip && \
    pip install --no-cache-dir git+https://github.com/wandb/wandb.git@$REF#egg=wandb[launch]

# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENV WANDB_AGENT_VERSION="$REF"

ENTRYPOINT ["wandb", "launch-agent"]
