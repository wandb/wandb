from ultralytics import YOLO
from wandb.integration.ultralytics import add_wandb_callback


def main():
    model = YOLO("yolov8n.pt")
    add_wandb_callback(model, max_validation_batches=2, enable_model_checkpointing=True)
    model.train(data="coco128.yaml", epochs=2, imgsz=640, batch=64)


if __name__ == "__main__":
    main()
