# Test for:
# - Semantic segmentation
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init(project="test-image-masks")


n = 40
m = 40

image = np.random.randint(255, size=(n, m, 3))
mask_list = []
for i in range(n):
    inner_list = []
    for j in range(m):
        v = 0
        if i < (n/2):
            v = 1
        if i > (n/2):
            v = 2
        if j < (m/2):
            v = v + 3
        if j > (m/2):
            v = v + 6
        inner_list.append(v)
    mask_list.append(inner_list)

mask_data = np.array(mask_list)
class_labels = {
                0 : "car",
                1 : "pedestrian",
                4 : "truck",
                5 : "tractor",
                7 : "barn",
                8 : "sign",
                }

for i in range(0,100):
    class_labels[i] = "tag " + str(i)

def gen_mask_img():
    mask_img = wandb.Image(np.array(image), masks={
        "predictions":
        {"mask_data": mask_data,
            }})
    return mask_img

def gen_mask_img_2():
    mask_img = wandb.Image(np.array(image), masks={
        "predictions_0":
        {"mask_data": mask_data,
            "class_labels": class_labels },
        "predictions_1":
        {"mask_data": mask_data,
            "class_labels": class_labels }}) 

    return mask_img 

def gen_mask_img_classless():
    mask_img = wandb.Image(np.array(image), masks={
        "predictions":
        {"mask_data": mask_data }})
    return mask_img

wandb.log({
    "mask_img_single": gen_mask_img(),
    "mask_img_no_class": gen_mask_img_classless(),
    "mask_img_list": [gen_mask_img(), gen_mask_img()],
})
