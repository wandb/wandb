import argparse
import os
import pathlib
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import prefect
import prefect.task_runners
import prefect_ray

import wandb

DATA_PATH = pathlib.Path(__file__).parent.absolute() / "_junk"
if not DATA_PATH.exists():
    DATA_PATH.mkdir(exist_ok=True)


parser = argparse.ArgumentParser()
parser.add_argument(
    "--task_runner",
    type=str,
    default="ray",
    choices=["ray", "concurrent", "sequential"],
)
args = parser.parse_args()

if args.task_runner == "ray":
    task_runner = prefect_ray.RayTaskRunner(init_kwargs={"num_cpus": 4})
elif args.task_runner == "concurrent":
    task_runner = prefect.task_runners.ConcurrentTaskRunner()
elif args.task_runner == "sequential":
    task_runner = prefect.task_runners.SequentialTaskRunner()
else:
    raise ValueError(f"Unknown task runner: {args.task_runner}")


@prefect.task
def generate_random_image(image_num: int) -> str:
    wandb_env_vars = {k: v for k, v in os.environ.items() if k.startswith("WANDB")}
    print(f"wandb_env_vars: {wandb_env_vars}")

    run = wandb.init(project="ray-prefect")
    pixels = np.random.randint(low=0, high=256, size=(100, 100, 3))

    means = np.zeros((10, 10, 3))
    for i in range(10):
        for j in range(10):
            for c in range(3):
                means[i, j, c] = np.mean(
                    pixels[i * 10 : (i + 1) * 10, j * 10 : (j + 1) * 10, c]
                )

    for i in range(10):
        for j in range(10):
            for c in range(3):
                pixels[i * 10 : (i + 1) * 10, j * 10 : (j + 1) * 10, c] = means[i, j, c]

    # save as png with name _junk/i.png and pad i to 2 digits
    save_path = DATA_PATH / f"{image_num:02d}.png"
    image = pixels.astype(np.uint8)
    plt.imsave(save_path, image)

    run.log({"image": wandb.Image(image)})

    # fig = plt.figure()
    # ax = fig.add_subplot(111)
    # ax.imshow(pixels)
    # plt.show()

    run.finish()

    return str(save_path)


@prefect.task
def combine_images(image_paths: List[str]) -> str:
    # load images from image_paths, and combine them into a single image
    # by stitching them together horizontally
    # store the combined image in _junk/combined.png
    # return the path to the combined image
    combined_image = np.array([plt.imread(image_path) for image_path in image_paths])
    combined_image = np.concatenate(combined_image, axis=1) * 255
    # print(combined_image.shape, combined_image)

    save_path = DATA_PATH / "combined.png"
    plt.imsave(save_path, combined_image.astype(np.uint8))

    return str(save_path)


@prefect.flow(task_runner=task_runner)
def image_pipeline():
    run = wandb.init(project="ray-prefect")
    logger = prefect.get_run_logger()

    image_path_futures = generate_random_image.map(range(10))
    # resolve futures
    image_paths = [str(f.result()) for f in image_path_futures]

    logger.info(f"raw image paths: {image_paths}")

    # get brightest pixel
    combined_image_path = combine_images(image_path_futures)
    logger.info(f"combined image path: {combined_image_path}")
    run.log({"combined_image": wandb.Image(plt.imread(combined_image_path))})
    run.finish()


image_pipeline()
