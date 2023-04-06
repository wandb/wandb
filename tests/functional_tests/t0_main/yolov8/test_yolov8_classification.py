from ultralytics.yolo.engine.model import YOLO
from wandb.integration.yolov8 import add_callbacks as add_wandb_callbacks


def main():
    model = YOLO("yolov8n-cls.pt")
    add_wandb_callbacks(model)
    model.train(
        data="mnist160",
        epochs=2,
        imgsz=32,
    )


if __name__ == "__main__":
    main()
