from ultralytics import YOLO
from wandb.yolov8 import add_wandb_callback


# Load a pretrained YOLO model (recommended for training)
model = YOLO(f"yolov8n-cls.pt")


# Add the Weights & Biases callback to the model.
# This will work for training, evaluation and prediction
add_wandb_callback(model, enable_model_checkpointing=True)


# Train the model using the 'coco128.yaml' dataset for 5 epochs
# Results after evaluating the validation batch would be logged
# to a W&B table at the end of each epoch
model.train(project="ultralytics", data="imagenette160", epochs=2, imgsz=640)


# Evaluate the model's performance on the validation set.
# The validation results are logged to a W&B table.
model.val()
