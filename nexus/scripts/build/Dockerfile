ARG PYTHON_VERSION=3.9
FROM --platform=linux/amd64 python:${PYTHON_VERSION}

# Set environment variables for pip to ensure only wheels are built
ENV PIP_NO_BINARY :all:
ENV PIP_NO_CACHE_DIR off
ENV PIP_WHEEL_DIR /wheels

ENV PATH $PATH:/usr/local/go/bin

# Create a directory for the project
WORKDIR /project/nexus

# Install any build dependencies
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Go
ARG GO_VERSION=1.21.0
RUN wget https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz && \
    rm go${GO_VERSION}.linux-amd64.tar.gz

RUN pip install wheel

CMD ["pip", "wheel", "."]
