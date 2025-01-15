# Ctrlplane CLI Docker Image

Official Docker image for the Ctrlplane CLI.

# Usage

## Pull the image

```sh
docker pull ctrlplane/cli:latest
```

or pull a specific version:

```sh
docker pull ctrlplane/cli:v0.1.0
```

## Run the image

```sh
docker run ctrlplane/cli ctrlc [your-command]
```

### Required environment variables

- `CTRLPLANE_API_KEY`: Your Ctrlplane API key.
- `CTRLPLANE_URL`: The URL of your Ctrlplane instance (e.g. `https://app.ctrlplane.dev`).

### Terraform sync

In order to sync Terraform resources into Ctrlplane, you need to set the following environment variables:

- `TFE_TOKEN`: Your Terraform Cloud API token.
- `TFE_ADDRESS` (optional): The URL of your Terraform Cloud instance (e.g. `https://app.terraform.io`). If not set, the default address (`https://app.terraform.io`) is used.

```sh
docker run ctrlplane/cli ctrlc sync terraform --organization my-org --workspace-id 2a7c5560-75c9-4dbe-be74-04ee33bf8188
```
