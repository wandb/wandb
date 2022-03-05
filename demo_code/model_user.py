
# Verify the you installed this branch with
# pip install -e ../ -U 
import wandb
from wandb.beta.workflows import use_model
from UserCode import *
import os

project = "chris_prep"
registered_model = "SKO Model" # change me to a value after manually making a registry

wandb.init(project=project)

model = use_model(f"{project}/{registered_model}:latest")
print(model)
print(model.model_obj())

# DO some cool stuff here.