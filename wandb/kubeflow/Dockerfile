FROM python:3.6-alpine

RUN apk add --no-cache yaml-dev openssl-dev libffi-dev build-base linux-headers git

RUN pip --no-cache-dir install https://storage.googleapis.com/ml-pipeline/release/0.1.3-rc.2/kfp.tar.gz git+git://github.com/wandb/client.git@56b4254f088139ff67543fd9a3d59615ca3e4c9e#egg=wandb[kubeflow]

ENTRYPOINT ["wandb", "tfjob"]