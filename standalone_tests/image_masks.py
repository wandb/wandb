# Test for:
# - Semantic segmentation
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init(project="test-image-masks")

image = np.random.randint(255, size=(400, 400, 3))
mask_data = np.random.randint(10, size=(400, 400))

def gen_mask_img():
    mask_img = wandb.Image(np.array(image), masks={
        "predictions":
        {"mask_data": mask_data,
            "class_labels": {
                0 : "car",
                1 : "pedestrian",
                }
            }})
    return mask_img

wandb.log({
    "mask_img_single": gen_mask_img(),
    "mask_img_list": [gen_mask_img(), gen_mask_img()],
})
