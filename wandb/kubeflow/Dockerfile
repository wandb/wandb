FROM python:3.6-alpine

RUN apk add --no-cache yaml-dev openssl-dev libffi-dev build-base linux-headers

RUN pip --no-cache-dir git+git://github.com/wandb/client.git@feature/kubeflow#egg=wandb[kubeflow]

ENTRYPOINT ["wandb", "tfjob"]