from wandb.yolov8 import add_callbacks
from ultralytics.yolo.engine.model import YOLO

def main():
    model = YOLO("yolov8n-seg.pt")
    model = add_callbacks(model)
    model.train(data="coco128-seg.yaml", epochs=2, imgsz=160,)


if __name__ == "__main__":
    main()