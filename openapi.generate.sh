#!/usr/bin/env bash

go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen -config openapi.client.yaml https://raw.githubusercontent.com/ctrlplanedev/ctrlplane/refs/heads/main/openapi.v1.json