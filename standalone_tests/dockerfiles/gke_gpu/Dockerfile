FROM nvidia/cuda:11.3.1-base-ubuntu20.04

# todo: rm once nvidia updates their docker images
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/3bf863cc.pub 3
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64/7fa2af80.pub

ARG PYTHON_VERSION=3.8

# todo: enable docker image layer caching on circleci
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    sudo \
    git \
    python${PYTHON_VERSION} \
    python3-pip \
    python${PYTHON_VERSION}-dev \
    build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

RUN mkdir /wandb
WORKDIR /wandb

RUN adduser --disabled-password --gecos '' --shell /bin/bash sdk \
    && chown -R sdk:sdk /wandb
RUN echo "sdk ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-sdk
USER sdk
ENV HOME=/home/sdk
RUN chmod 777 /home/sdk

# clone wandb/client repository and install wandb sdk
RUN git clone https://github.com/wandb/client.git /wandb/client \
    && cd /wandb/client \
    && pip install -e . \
    && pip install numpy torch torchvision --no-cache-dir
# todo: replace with a proper tox+yea setup with
#    && pip install -r requirements_dev.txt \

WORKDIR /wandb/client
CMD ["python", "standalone_tests/pytorch_bare.py"]
