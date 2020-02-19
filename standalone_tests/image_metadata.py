# Test for:
# - Semantic segmentation
# - Bounding Boxes
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init()

image = np.random.randint(255, size=(400, 400, 3))
mask_data = np.random.randint(10, size=(400, 400))

def f_n_m(f, n, m):
    return [[f(i,j) for i in range(0,n)] for j in range(0,m)]

def fun(i,j):
    n_i = i / 400
    n_j = j / 400

    return [(sin(n_i * 20 * pi) ) * 255, 
            (sin(n_j * 20 * pi) ) * 255, 
            (cos(n_j * 20 * pi)  * cos(n_i * 20 * pi)) * 255]

fun_image = np.array( f_n_m(fun, 400, 400))

def gen_mask_img():
    mask_img = wandb.Image(np.array(image), masks=[{
        "mask_data": mask_data,
        "class_labels": {
            0 : "car", 
            1 : "pedestrian",
        }
    }])
    return mask_img


# 2D Bounding Boxes
def gen_box():
    box = {"position": {
        "middle": [100 + random.randint(-50,50), 100 + random.randint(-50,50)],
        "width": 100 + random.randint(-50,50),
        "height": 100 + random.randint(-50,50),
    },
     "class_label" : "car",
     "box_caption": "car conf 0.7",
     "scores" : {
         "acc": 0.7
         }
    }

    return box

def gen_box_img():
    box_img = wandb.Image(image, boxes=[gen_box() for i in range(1,100)] )
    return box_img

wandb.log({
    "mask_img_single": gen_mask_img(),
    # "mask_img_list": [gen_mask_img(), gen_mask_img()],
    # "box_img_list": [gen_box_img()],
    # "box_img_single": gen_box_img(),
})
