from ultralytics.yolo.engine.model import YOLO
from wandb.yolov8 import add_callbacks


def main():
    model = YOLO("yolov8n-cls.pt")
    model = add_callbacks(model)
    model.train(
        data="mnist160",
        epochs=2,
        imgsz=32,
    )


if __name__ == "__main__":
    main()
