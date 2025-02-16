FROM python:3.12-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Install Go.
COPY --from=golang:1.22-alpine /usr/local/go/ /usr/local/go/
COPY scripts /opt/ns/scripts

# Set the home directory of the container
ENV HOME=/opt/ns

# Set Go environment paths
ENV GOPATH="/go"
ENV PATH="$GOPATH/bin:/usr/local/go/bin:$PATH"

# Set up Go workspace directories
RUN mkdir -p "$GOPATH/src" "$GOPATH/bin" && chmod -R 777 "$GOPATH"

# install git
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git gcc python3-dev \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

RUN apt-get update && apt-get install vim -y \
    && apt-get install sysstat -y \
    && apt-get install jq -y \
    && apt-get install procps -y \
    && apt-get install -y libsndfile1 ffmpeg \
    && apt-get install -y linux-perf


# Add build argument for wandb version
ARG WANDB_VERSION=""

# Install wandb based on the provided version or the latest if no version is provided
RUN pip install --upgrade pip && \
    if [ -z "$WANDB_VERSION" ]; then pip install wandb -qU; else pip install "wandb==$WANDB_VERSION" -qU; fi

RUN pip install --no-cache-dir wandb[media]

# Install Go pprof
RUN go install github.com/google/pprof@latest

# Install py-spy
RUN pip install --no-cache-dir py-spy


CMD ["sleep", "10000000"]
