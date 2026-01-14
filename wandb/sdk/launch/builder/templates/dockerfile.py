DOCKERFILE_TEMPLATE = """
# ----- stage 1: build -----
FROM {py_build_image} as build

# requirements section depends on pip vs conda, and presence of buildx
ENV PIP_PROGRESS_BAR off
{requirements_section}

# ----- stage 2: base -----
{base_setup}

COPY --from=build /env /env
ENV PATH="/env/bin:$PATH"

ENV SHELL /bin/bash

# some resources (eg sagemaker) must run on root
{user_setup}

WORKDIR {workdir}
RUN chown -R {uid} {workdir}

# make artifacts cache dir unrelated to build
RUN mkdir -p {workdir}/.cache && chown -R {uid} {workdir}/.cache

# copy code/etc
COPY --chown={uid} src/ {workdir}

ENV PYTHONUNBUFFERED=1

{entrypoint_section}
"""

# this goes into base_setup in TEMPLATE
PYTHON_SETUP_TEMPLATE = """
FROM {py_base_image} as base
"""

# this goes into base_setup in TEMPLATE
ACCELERATOR_SETUP_TEMPLATE = """
FROM {accelerator_base_image} as base

# make non-interactive so build doesn't block on questions
ENV DEBIAN_FRONTEND=noninteractive

# install python
RUN apt-get update -qq && apt-get install --no-install-recommends -y \
    {python_packages} \
    && apt-get -qq purge && apt-get -qq clean \
    && rm -rf /var/lib/apt/lists/*

# make sure `python` points at the right version
RUN update-alternatives --install /usr/bin/python python /usr/bin/python{py_version} 1 \
    && update-alternatives --install /usr/local/bin/python python /usr/bin/python{py_version} 1
"""

# this goes into requirements_section in TEMPLATE
PIP_TEMPLATE = """
RUN python -m venv /env
# make sure we install into the env
ENV PATH="/env/bin:$PATH"

COPY {requirements_files} ./
{buildx_optional_prefix} {pip_install}
"""

# this goes into requirements_section in TEMPLATE
CONDA_TEMPLATE = """
COPY src/environment.yml .
{buildx_optional_prefix} conda env create -f environment.yml -n env

# pack the environment so that we can transfer to the base image
RUN conda install -c conda-forge conda-pack
RUN conda pack -n env -o /tmp/env.tar && \
    mkdir /env && cd /env && tar xf /tmp/env.tar && \
    rm /tmp/env.tar
RUN /env/bin/conda-unpack
"""

USER_CREATE_TEMPLATE = """
RUN useradd \
    --create-home \
    --no-log-init \
    --shell /bin/bash \
    --gid 0 \
    --uid {uid} \
    {user} || echo ""
"""

ENTRYPOINT_TEMPLATE = """
ENTRYPOINT {entrypoint}
"""
