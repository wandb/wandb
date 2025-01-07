FROM python:3.9-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# Install Go.
COPY --from=golang:1.22-alpine /usr/local/go/ /usr/local/go/
ENV PATH="/usr/local/go/bin:${PATH}"

# Set Go environment paths
ENV GOPATH /go
ENV PATH $GOPATH/bin:/usr/local/go/bin:$PATH

# Set up Go workspace directories
RUN mkdir -p "$GOPATH/src" "$GOPATH/bin" && chmod -R 777 "$GOPATH"

# install git
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git gcc python3-dev \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

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
