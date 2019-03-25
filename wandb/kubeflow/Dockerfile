FROM python:3.6-alpine as build

RUN apk add --no-cache yaml-dev openssl-dev libffi-dev build-base linux-headers go curl

RUN mkdir -p /root/go/src/github.com/kubeflow/arena

WORKDIR /root/go/src/github.com/kubeflow/arena
COPY arena .

RUN make

RUN wget https://storage.googleapis.com/kubernetes-helm/helm-v2.11.0-linux-amd64.tar.gz && \
    tar -xvf helm-v2.11.0-linux-amd64.tar.gz && \
    mv linux-amd64/helm /usr/local/bin/helm && \
    chmod u+x /usr/local/bin/helm

ENV K8S_VERSION v1.11.2
RUN curl -o /usr/local/bin/kubectl https://storage.googleapis.com/kubernetes-release/release/${K8S_VERSION}/bin/linux/amd64/kubectl && chmod +x /usr/local/bin/kubectl

COPY dist /dist
RUN pip install --install-option="--prefix=/install" --find-links=/dist wandb[kubeflow]

FROM python:3.6-alpine

COPY --from=build /root/go/src/github.com/kubeflow/arena/bin/arena /usr/local/bin/arena

COPY --from=build /usr/local/bin/helm /usr/local/bin/helm

COPY --from=build /root/go/src/github.com/kubeflow/arena/kubernetes-artifacts /root/kubernetes-artifacts

COPY --from=build /usr/local/bin/kubectl /usr/local/bin/kubectl

COPY --from=build /root/go/src/github.com/kubeflow/arena/charts /charts

COPY --from=build /install /usr/local

RUN apk add --no-cache bash

RUN mkdir /ml

ENTRYPOINT ["python", "-m", "wandb.kubeflow.arena"]