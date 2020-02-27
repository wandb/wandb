# Test for:
# - Semantic segmentation
import wandb
import random
from math import sin, cos, pi
import numpy as np

wandb.init(project="test-bounding-box")

IMG_SIZE = 400
image = np.random.randint(255, size=(IMG_SIZE, IMG_SIZE, 3))


# Box with middle with height
def gen_box_type_1(point_range, pixel=None):
    half = point_range / 2.0
    middle  = [half + (random.random() - 0.5) * half, half + (random.random() - 0.5) * half]
    box = {
            "position": {
                "middle": middle,
                "width":  (random.random() - 0.5) * half,
                "height":  (random.random() - 0.5) * half,
                },
            "class_label" : "car",
            "box_caption": "car conf 0.7",
            "scores" : {
                "acc": 0.7
                }
            }

    if pixel:
        box["domain"] = "pixel"

    return box

def clamp(x, minmax):
    max(x, minmax[0], minmax[1])

# Box  with min/max x/y
def gen_box_type_2(point_range, pixel=None):
    half = point_range / 2.0
    width = max(random.random() * half, point_range * 0.1)
    height = max(random.random() * half, point_range * 0.1)
    x = (point_range - width) * random.random()
    y = (point_range - height) * random.random()
    box = { "position": {
                "minX": x,
                "maxX": x + width,
                "minY": y,
                "maxY": y + height,
                },
            "class_label" : "car",
            "box_caption": "car conf 0.7",
            "scores" : {
                "acc": 0.7
                }
            }

    if pixel:
        box["domain"] = "pixel"

    return box

def gen_box_img_type_1(vrange=1, box_count=100):
    box_img = wandb.Image(image, boxes=[gen_box_type_1(vrange) for i in range(1,box_count)])
    return box_img

def gen_box_img_type_2(vrange=1, box_count=100):
    box_img = wandb.Image(image, boxes=[gen_box_type_2(vrange) for i in range(1,box_count)] )
    return box_img


# Generates an img with each box type that should all render the same
def balanced_corners_portrait():
    box_w = 40
    box_h = 20
    padding = 20
    img_width = 400
    img_height = 200
    image = np.random.randint(255, size=(img_height, img_width, 3))

    box_corners = [
            [padding, padding],
            [padding, img_height - box_h - padding],
            [img_width - box_w - padding, padding],
            [img_width -  box_w - padding,
                img_height - box_h - padding]]


    img_pixel = wandb.Image(image, boxes=[
        {"position": {
            "middle": [x + box_w/2.0, y + box_h/2.0],
            "width":  box_w,
            "height":  box_h,
            },
        "class_label" : "car",
        "box_caption": "car conf 0.7",
        "scores" : {
            "acc": 0.7
            },
        "domain": "pixel"
        }

        for [x,y] in box_corners ])

    img_norm_domain = wandb.Image(image, boxes=[
        {"position": {
            "middle": [(x + box_w/2.0)/img_width, (y + box_h/2.0) / img_height],
            "width":  float(box_w) / img_width,
            "height":  float(box_h) / img_height,
            },
        "class_label" : "car",
        "box_caption": "car conf 0.7",
        "scores" : {
            "acc": 0.7
            }
        }

        for [x,y] in box_corners])

    img_min_max_pixel = wandb.Image(image, boxes=[
        {"position": {
            "minX": x,
            "maxX": x + box_w,
            "minY": y,
            "maxY": y + box_h,
            },
        "class_label" : "car",
        "box_caption": "car conf 0.7",
        "scores" : {
            "acc": 0.7
            },
        "domain": "pixel"
        }

        for [x,y] in box_corners])

    img_min_max_norm_domain = wandb.Image(image, boxes=[
        {"position": {
            "minX": float(x)/img_width,
            "maxX": float(x + box_w)/img_width,
            "minY": float(y)/img_height,
            "maxY": float(y + box_h)/img_height,
            },
        "class_label" : "car",
        "box_caption": "car conf 0.7",
        "scores" : {
            "acc": 0.7
            }
        }

        for [x,y] in box_corners])

    return [img_pixel, 
            img_norm_domain,
            img_min_max_pixel,
            img_min_max_norm_domain]

wandb.log({
    "balanced_corners_portrait": balanced_corners_portrait()
    # "box_img_list": [gen_box_img_type_1(), gen_box_img_type_2()],
    # "box_img_single": gen_box_img_type_1(),
    # "box_2_img_list": [gen_box_img_type_2()],
    # "box_2_img_single": gen_box_img_type_2(),

    # "box_type_1_pixel": gen_box_img_type_1(IMG_SIZE, True),
    # "box_type_2_pixel": gen_box_img_type_2(IMG_SIZE, True),
    })
