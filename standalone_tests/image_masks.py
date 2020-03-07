# Test for:
# - Semantic segmentation
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init(project="test-image-masks")

image = np.random.randint(255, size=(400, 400, 3))
mask_list = []
n = 400
m = 400
for i in range(n):
    inner_list = []
    for j in range(m):
        v = 0
        if i < 200:
            v = 1
        if i > 200:
            v = 2
        if j < 200:
            v = v + 3
        if j > 200:
            v = v + 6
        inner_list.append(v)
    mask_list.append(inner_list)

mask_data = np.array(mask_list)

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
