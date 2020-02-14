# Test for:
# - Semantic segmentation
# - Bounding Boxes
import wandb
import numpy as np

wandb.init()

image = np.random.randint(255, size=(28, 28, 3))
mask_data = np.random.randint(10, size=(28, 28))

def gen_mask_img():
    mask_img = wandb.Image(image, masks=[{
        "mask_data": mask_data,
        "class_labels": {
            0 : "car", 
            1 : "pedestrian",
        }
    }])
    return mask_img


# 2D Bounding Boxes

def gen_box_img():
    box_img = wandb.Image(image, boxes=[
        {
            "position": {
                "middle": [100, 100],
                "width": 200,
                "height": 100
            },
             "class_label" : "car",
             "box_caption": "car conf 0.7",
             "scores" : {
                 "acc": 0.7
             },
        }
    ])
    return box_img

wandb.log({
    "mask_img_single": gen_mask_img(),
    "mask_img_list": [gen_mask_img(), gen_mask_img()],
    "box_img_list": [gen_box_img()],
    "box_img_single": gen_box_img(),
})
