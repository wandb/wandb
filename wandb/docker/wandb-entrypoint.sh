#!/bin/sh
set -e

wandb="\x1b[34m\x1b[1mwandb\x1b[0m"
/bin/echo -e "${wandb}: Checking image for required packages."

if ! [ -x "$(command -v python)" ]; then
    /bin/echo -e "${wandb}: python not installed, can't use wandb with this image."
    exit 1
fi

if ! [ -x "$(command -v wandb)" ]; then
    /bin/echo -e "${wandb}: wandb not installed, installing."
    pip install wandb --upgrade
else
    ver=$(wandb --version)
    /bin/echo -e "${wandb}: Found $ver"
fi

if [ "$WANDB_ENSURE_JUPYTER" = "1" ]; then
    if ! [ -x "$(command -v jupyter-lab)" ]; then
        /bin/echo -e "${wandb}: jupyter not installed, installing."
        pip install jupyterlab
        /bin/echo -e "${wandb}: starting jupyter, you can access it at: http://127.0.0.1:8888"
    fi
fi

if ! [ -z "$WANDB_COMMAND" ]; then
    /bin/echo $WANDB_COMMAND >> ~/.bash_history
    /bin/echo -e "${wandb}: Command added to history, press up arrow to access it."
    /bin/echo -e "${wandb}: $WANDB_COMMAND"
fi
exec "$@"