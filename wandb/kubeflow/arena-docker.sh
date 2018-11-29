#!/bin/bash

docker run -v ~/.kube:/root/.kube \
    -v ~/.config/gcloud:/root/.config/gcloud \
    --entrypoint arena wandb/arena "$@"
