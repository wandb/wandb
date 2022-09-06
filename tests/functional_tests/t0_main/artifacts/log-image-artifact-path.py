import numpy as np
import wandb


def make_image():
    return wandb.Image(np.random.randint(255, size=(32, 32)))


def main():
    # Base Case
    with wandb.init() as run:
        run.log({"image": make_image()})

    # With Logged Target
    with wandb.init() as run:
        art = wandb.Artifact("examples", "images")
        image = make_image()
        art.add(image, "image")
        run.log_artifact(art)
        run.log({"image": image})


if __name__ == "__main__":
    main()
