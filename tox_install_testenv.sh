#!/bin/bash

pip install -f https://download.pytorch.org/whl/torch_stable.html $1 $2
pip install -f $1 -r$3/wandb/sweeps/requirements.txt 
