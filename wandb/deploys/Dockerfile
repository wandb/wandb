FROM python:3.9-slim-bullseye

RUN apt-get update && apt-get upgrade && apt-get install
# install git
RUN apt-get install -y git
RUN rm -rf /var/lib/apt/lists

# required pip packages
RUN pip install git+https://github.com/wandb/client.git@launch/general-launch-agent
RUN pip install wandb[launch]
RUN pip install kubernetes
# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENTRYPOINT ["wandb", "launch-agent"]
