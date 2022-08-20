FROM python:3.9-slim-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# install git
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*

# required pip packages
RUN pip install --no-cache-dir wandb[launch]
# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENTRYPOINT ["wandb", "launch-agent"]
