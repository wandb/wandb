FROM nvidia/cuda:12.2.0-runtime-ubuntu20.04

# Mount a volume for the Go build cache
VOLUME /root/.cache/go-build

ENV PATH $PATH:/usr/local/go/bin

# Create a directory for the project
WORKDIR /project/core

# Install any build dependencies
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    libffi-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Go
ARG GO_VERSION=1.21.6
RUN wget https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz && \
    rm go${GO_VERSION}.linux-amd64.tar.gz

CMD go build -ldflags="-s -w -X main.commit=${COMMIT}" -o ${CORE_PATH} cmd/core/main.go
