# Test for:
# - Semantic segmentation
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init(project="test-bounding-box")

image = np.random.randint(255, size=(400, 400, 3))

# 2D Bounding Boxes
def gen_box_type_2():
    box = {"position": {
        "minX": 100 + random.randint(-50,0),
        "maxX": 100 + random.randint(0,50),
        "minY": 100 + random.randint(-50,0),
        "maxY": 100 + random.randint(0,50),
    },
     "class_label" : "car",
     "box_caption": "car conf 0.7",
     "scores" : {
         "acc": 0.7
         }
    }

    return box

# 2D Bounding Boxes
def gen_box_type_1():
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

def gen_box_img_type_1():
    box_img = wandb.Image(image, boxes=[gen_box_type_1() for i in range(1,100)] )
    return box_img

def gen_box_img_type_2():
    box_img = wandb.Image(image, boxes=[gen_box_type_2() for i in range(1,100)] )
    return box_img

wandb.log({
    "box_img_list": [gen_box_img_type_1(), gen_box_img_type_2()],
    "box_img_single": gen_box_img_type_1(),
    "box_2_img_list": [gen_box_img_type_2()],
    "box_2_img_single": gen_box_img_type_2()
})
