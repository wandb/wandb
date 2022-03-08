FROM python:3.9-buster
USER root
RUN mkdir -p /home/launch_agent
WORKDIR /home/launch_agent

RUN apt-get update
RUN apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
RUN echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get update
RUN apt-get install -y docker-ce docker-ce-cli containerd.io

RUN pip install git+https://github.com/wandb/client.git@launch/general-launch-agent
RUN pip install wandb[launch]

ENTRYPOINT ["wandb", "launch-agent"]
