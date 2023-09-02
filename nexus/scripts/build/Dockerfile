#ARG PYTHON_VERSION=3.9
#ARG PLATFORM=amd64
#FROM --platform=linux/${PLATFORM} python:${PYTHON_VERSION}
#FROM quay.io/pypa/manylinux2014_x86_64:latest
#FROM nvidia/cuda:12.2.0-runtime-ubuntu20.04
FROM nvidia/cuda:12.2.0-devel-ubuntu20.04

# Mount a volume for the Go build cache
VOLUME /root/.cache/go-build

ENV PATH $PATH:/usr/local/go/bin

# Create a directory for the project
WORKDIR /project/nexus

# Install any build dependencies
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    libffi-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN #yum install -y wget && yum clean all

# Install Go
ARG GO_VERSION=1.21.0
RUN wget https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz && \
    rm go${GO_VERSION}.linux-amd64.tar.gz

# Download and setup NVML
#RUN yum-config-manager \
#    --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/cuda-rhel7.repo && \
#    yum-config-manager \
#    --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel7/x86_64/cuda-rhel7.repo && \
#    yum install -y nvidia-driver-latest-dkms cuda cuda-drivers && \
#    yum clean all

#ENV LD_LIBRARY_PATH /usr/local/nvidia/lib64:${LD_LIBRARY_PATH}

CMD /bin/bash
#CMD go build -ldflags="-s -w -X main.commit=${COMMIT}" -o ${NEXUS_PATH} cmd/nexus/main.go
