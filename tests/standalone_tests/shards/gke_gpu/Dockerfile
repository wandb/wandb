FROM nvidia/cuda:11.3.1-runtime-ubuntu20.04

# todo: rm once nvidia updates their docker images
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/3bf863cc.pub 3
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64/7fa2af80.pub

ARG DEBIAN_FRONTEND=noninteractive

ARG PYTHON_VERSION=3.8
ARG GIT_BRANCH=master
ARG TOX_VERSION=3.24.0
ARG UTC_DATE

# todo: enable docker image layer caching on circleci
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim \
    curl \
    ca-certificates \
    sudo \
    git \
    python${PYTHON_VERSION} \
    python3-pip \
    python${PYTHON_VERSION}-dev \
    build-essential \
    libsndfile1 \
    ffmpeg \
    libcudnn8 \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

RUN mkdir /wandb
WORKDIR /wandb

RUN adduser --disabled-password --gecos '' --shell /bin/bash sdk \
    && adduser sdk sudo\
    && chown -R sdk:sdk /wandb
RUN echo "sdk ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-sdk
USER sdk
ENV HOME=/home/sdk
RUN chmod 777 /home/sdk

# clone wandb/wandb repository and install wandb sdk
RUN git clone https://github.com/wandb/wandb.git /wandb/wandb \
    && cd /wandb/wandb \
    && git checkout ${GIT_BRANCH} \
    && pip install --upgrade pip \
    && pip install tox==${TOX_VERSION} --no-cache-dir

RUN PATH=/home/sdk/.local/bin:$PATH

WORKDIR /wandb/wandb
# use torch wheels with CUDA 11.3 support
RUN sed -i -e 's/whl\/cpu/whl\/cu113/g' tox.ini
ENV DATE=$UTC_DATE
#CMD ["tail", "-f", "/dev/null"]
CMD ["python", "-m", "tox", "-v", "-e", "standalone-gpu-py38,pod-store"]
