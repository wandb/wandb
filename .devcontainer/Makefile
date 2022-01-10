TAG := $(if $(TAG),$(TAG),$(shell date +"%Y-%m-%d-%H"))

.EXPORT_ALL_VARIABLES:
# You must be logged into dockerhub for this to work `docker login -u XXX -p YYY`
# 
build:
	docker buildx build . -t wandb/devcontainer-cli:latest -t wandb/devcontainer-cli:${TAG} \
		--platform=linux/arm64,linux/amd64 --push

dev:
	docker run -it -v $(CURDIR)/../:/workspaces/client -v tox-cache:/workspaces/client.tox:cached --privileged wandb/devcontainer-cli zsh