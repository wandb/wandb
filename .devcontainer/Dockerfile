# Source: https://github.com/microsoft/vscode-dev-containers/tree/main/containers/miniconda
ARG VARIANT="3"
ARG NODE_VERSION="16"
FROM mcr.microsoft.com/vscode/devcontainers/miniconda:${VARIANT}

ARG USERNAME=vscode
ARG NODE_VERSION="16" \
    PYTHON_VERSION="py39" \
    PYTHON_PACKAGES="py36 py37 py38 py39 py310" \
    DOCKER_VERSION="latest"

USER root

# Purge man-db to speed up installs and slim the build
RUN apt-get purge -y --auto-remove man-db

# Copy our essential scripts first to leverage docker caching
COPY scripts/base/* scripts/clis/*.sh /tmp/scripts/

ENV NVM_DIR=/usr/local/share/nvm \
    PYENV_ROOT="/home/$USERNAME/.pyenv" \
    DOCKER_BUILDKIT=1 \
    SHELL=/usr/bin/zsh

ENV PATH="$PYENV_ROOT/bin:$PYENV_ROOT/shims:$PATH"

# Install clis
RUN apt-get update \
    && bash /tmp/scripts/docker-in-docker-debian.sh "true" "${USERNAME}" "true" "${DOCKER_VERSION}"  \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# VSCode dev tools are installed with pipx
# TODO: CONDA_EXE isn't persisting / being used and it breaks activation
ENV PIPX_HOME=/usr/local/py-utils
ENV PIPX_BIN_DIR=${PIPX_HOME}/bin \
    DEFAULT_PYTHON=$PYTHON_VERSION \
    CONDA_EXE=mamba

# Install languages
COPY scripts/languages/* /tmp/scripts/
RUN --mount=type=cache,target=/opt/conda/pkgs,uid=1000,gid=900 \
    su $USERNAME -c "bash --login /tmp/scripts/python-versions-conda.sh ${USERNAME}"

USER ${USERNAME}

# Install wandb tools
COPY scripts/user/* /tmp/scripts/
RUN bash /tmp/scripts/wandb-tools-debian.sh \
    && mkdir -p /usr/local/etc/vscode-dev-containers/ \
    && sudo mv -f /tmp/scripts/first-run-notice.txt /usr/local/etc/vscode-dev-containers/

# Setup pyenv, cool shell stuff, and cleanup
RUN --mount=type=cache,target=/opt/conda/pkgs,uid=1000,gid=900 \
    bash /tmp/scripts/zsh-debian.sh \
    && bash --login /tmp/scripts/configure-pyenv-debian.sh ${PYTHON_VERSION}
# && sudo rm -rf /tmp/*

# Mount for docker-in-docker
VOLUME [ "/var/lib/docker" ]

ENTRYPOINT [ "/usr/local/share/docker-init.sh" ]
CMD [ "sleep", "infinity" ]