# W&B VSCode CLI Dev Container

This container is meant to serve as a base for all W&B CLI development. You can run this container locally [with VSCode](https://code.visualstudio.com/docs/remote/remote-overview) or launch this into [Github Code Spaces](https://github.com/features/codespaces).

## Features

- Debian Bullseye
- Node 16
- MiniConda 3 
- Python 3.6, 3.7, 3.8, 3.9 (default), 3.10
- Pyenv and NVM
- Docker

## Conda, Mamba, and Virtual Envs

This container is based on [MiniConda](https://docs.conda.io/en/latest/miniconda.html).  It allows us to create virtual environments in different versions of python.  

> We may switch to [MicroMamba](https://gist.github.com/wolfv/fe1ea521979973ab1d016d95a589dcde) as it's even slimmer and faster.

For now, all you need to know is:

```shell
conda activate py36
# Now you are in a python 3.6 virtualenv & can use pip or tox
conda activate py39
# Now you're back in the default environment
```

The default environment is currently python 3.9.  We install a bunch of extra packages in this environment for testing such as JupyterLab and all the ML Frameworks.  If you need to test in different python environments you'll likely need to run `pip install -r requirements_dev.txt` after activating it.

### Some quick notes on why conda is useful

Conda provides pre-compiled binaries for most packages we use.  This means we can quickly install them (if we install them from conda), it also means it's confusing to know which packages are from conda and which ones are from pip.

## Local dev server

If want to run `wandb local` to test against a local server, simply run it.  We pull down the image ahead of time so it should be snappy.  You can also access the container via http://localhost:8080 on your laptop as it automatically forwards ports. 

## Remote Containers

VS Code allows you to start dev containers locally on your laptop.  In my limited testing the performance wasn't great, but the issues are likely related to M1 macs and docker and will hopefully improve.  You can try a local container by selecting `Remote-Containers: Rebuild and Reopen in Container` from the VS Code command prompt.

## Code Spaces

Code Spaces make it easy to quickly spin up a development environment in the cloud and connect it to your local machine.  This container serves as a reference environment for any equivalent native dev set ups.  Code Spaces provide a number of benefits and some drawbacks:

### Benefits

1. Onboarding - new devs can get up and running in a well known environment in minutes.
2. Collaboration - pair programming or accessing services running in the container can be shared with other devs.
3. Unified Environment - we can centrally update python, node, etc without requiring dev action.

### Drawbacks

1. VS Code Only - not all devs use vscode.  You can still create an SSH tunnel into the codespace and run other IDE's but the experience isn't great
2. Network Latency - you can still access services over localhost, but the data is tunneled to the codespace.  This can slow down dev tools like vite.
3. No offine mode - you can't develop on a plane or over a spotty internet connection

## Networking

TODO: Document how to develop against other networks.

## Making Changes

As we update our core run times we should update both this README and the Dockerfile with the updated versions.  When making modifications to this environment we follow these principles:

1. Cleanup after updating debian packages, i.e. `apt-get clean -y && rm -rf /var/lib/apt/lists/*`
2. Ensure your build steps support arm64 and amd64 (you can source build-utils-debian.sh to get $architecture)
3. There are 3 main steps to the build: clis, languages, and user. Any additional scripts should be added to the appropriate folder.
4. Use the onCreateCommand to install dependencies and other 1 time commands that need the core repo.
5. Document what and when core libraries should be updated

Running `make build` in this directory will create a new container and push it to dockerhub assuming you have access. We'll be automating this step in the future.  

## SSH

If you need to push or pull from other private registries you'll need to add an ssh key to the installation.

It's best to configure [a separate SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent) for your code space so you can access all our repos. See [Private Packages & SSH](https://dev.to/aws-heroes/getting-started-with-github-codespaces-from-a-serverless-perspective-171k) on this page for details.
