import argparse
import cProfile
import contextlib
import dataclasses
from pathlib import Path
import time
from typing import Iterable, Iterator, MutableSequence

import tqdm
import numpy as np
import wandb

parser = argparse.ArgumentParser(description="Try to reproduce Motorola's slow upload issues")
parser.add_argument("--n-images", type=float, required=True, help="number of files to upload")
parser.add_argument("--image-kb", type=float, required=True, help="approximate size of files to upload")
parser.add_argument("--double-log", action='store_true', help="whether to log images directly to the artifact as well as through the table")
parser.add_argument("--all-in-memory-at-once", action='store_true', help="whether to force all images to reside in memory for the duration of the program")
parser.add_argument("--profile-output", type=Path, default=Path('run.profile'))
parser.add_argument("--random-seed", type=int, default=None)

@contextlib.contextmanager
def profiling(filepath: str):
    profile = cProfile.Profile()
    profile.enable()
    yield
    profile.disable()
    profile.dump_stats(filepath)

def make_images(num_images: int, kb: float, all_in_memory_at_once: bool = False) -> Iterable[np.ndarray]:
    dim = int(np.sqrt(kb * 1000))
    iterator = (np.random.randint(256, size=(dim, dim), dtype=np.uint8) for _ in range(num_images))
    if all_in_memory_at_once:
        return list(iterator)
    else:
        return iterator

@contextlib.contextmanager
def log_time(d: dict, name: str):
    start = time.time()
    yield
    elapsed = time.time() - start
    print('{} took {} sec'.format(name, elapsed))
    d[name] = elapsed

def _main(num_images: int, kb: float, double_log: bool, all_in_memory_at_once: bool, random_seed: int, profile_output: Path):
    if random_seed is not None:
        np.random.seed(random_seed)

    with profiling(profile_output):
        images = make_images(num_images=num_images, kb=kb, all_in_memory_at_once=all_in_memory_at_once)
        d = {
            'num_images': num_images,
            'image_kb': kb,
            'double_log': double_log,
            'all_in_memory_at_once': all_in_memory_at_once,
            'random_seed': random_seed,
        }
        with wandb.init(project="slow_artifact_upload_0407", job_type=f"{kb}-uint8") as run:

            run.config.update(d)
            table = wandb.Table(columns=["id", "image"])
            artifact = wandb.Artifact(name=f"{num_images}_numpy_table_artifact", type="dataset")

            with log_time(d, 'total_sec'):
                with log_time(d, 'log_images_sec'):
                    for i, arr in tqdm.tqdm(enumerate(images)):
                        table.add_data(i, wandb.Image(arr))
                        if double_log:
                            run.log({f"image_{i}": wandb.Image(arr)})
                with log_time(d, 'add_table_sec'):
                    artifact.add(table, name="my-table")
                with log_time(d, 'log_artifact_sec'):
                    run.log_artifact(artifact)
                with log_time(d, 'artifact_wait_sec'):
                    artifact.wait()

            run.log(d)

def main(args):
    _main(
        num_images=int(args.n_images),
        kb=args.image_kb,
        double_log=args.double_log,
        all_in_memory_at_once=args.all_in_memory_at_once,
        random_seed=args.random_seed,
        profile_output=args.profile_output,
    )


if __name__ == "__main__":
    main(parser.parse_args())
