from ultralytics.yolo.engine.model import YOLO
from wandb.integration.yolov8 import add_callbacks as add_wandb_callbacks


def main():
    model = YOLO("yolov8n.pt")
    add_wandb_callbacks(model)
    model.train(
        data="coco128.yaml",
        epochs=2,
        imgsz=160,
    )


if __name__ == "__main__":
    main()
