FROM nvidia/cuda:11.3.1-base-ubuntu20.04

# todo: rm once nvidia updates their docker images
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/3bf863cc.pub 3
RUN apt-key adv --fetch-keys \
    https://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64/7fa2af80.pub

ARG PYTHON_VERSION=3.8

# Install some basic utilities
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
    && pip install -e .

CMD ["python"]

## Set up the Conda environment instead?
#ENV CONDA_AUTO_UPDATE_CONDA=false \
#    PATH=/home/user/miniconda/bin:$PATH
#COPY environment.yml /app/environment.yml
#RUN curl -sLo ~/miniconda.sh https://repo.continuum.io/miniconda/Miniconda3-py39_4.10.3-Linux-x86_64.sh \
# && chmod +x ~/miniconda.sh \
# && ~/miniconda.sh -b -p ~/miniconda \
# && rm ~/miniconda.sh \
# && conda env update -n base -f /app/environment.yml \
# && rm /app/environment.yml \
# && conda clean -ya
#
## Set the default command to python3
#CMD ["python3"]
