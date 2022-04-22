import argparse
from typing import Callable
import tqdm
import numpy as np
import wandb

Run = wandb.wandb_sdk.wandb_run.Run

def main_runlog(run: Run, make_image: Callable[[], np.ndarray], n_images: int) -> None:
    for _ in tqdm.tqdm(range(n_images)):
        run.log({f'image': wandb.Image(make_image())})

def main_artifact(run: Run, make_image: Callable[[], np.ndarray], n_images: int) -> None:
    artifact = wandb.Artifact(name='slow-upload-repro-artifact', type='dataset')
    for step in tqdm.tqdm(range(n_images)):
        artifact.add(wandb.Image(make_image()), name=f'image_{step}')
    run.log_artifact(artifact)
    artifact.wait()

def main_artifacttable(run: Run, make_image: Callable[[], np.ndarray], n_images: int) -> None:
    artifact = wandb.Artifact(name='slow-upload-repro-artifacttable', type='dataset')
    table = wandb.Table(columns=['image'])
    for _ in tqdm.tqdm(range(n_images)):
        table.add_data(wandb.Image(make_image()))
    artifact.add(table, name='my-table')
    run.log_artifact(artifact)
    artifact.wait()

MAIN_FUNCS = {
    'runlog': main_runlog,
    'artifact': main_artifact,
    'artifacttable': main_artifacttable,
}

parser = argparse.ArgumentParser()
parser.add_argument('method', choices=sorted(MAIN_FUNCS.keys()))
parser.add_argument('-s', '--image-size-kb', type=int, required=True)
parser.add_argument('-n', '--num-images', type=int, required=True)

def main(args):
    dim = int(np.sqrt(args.image_size_kb * 1000))
    make_image = lambda: np.random.randint(256, size=(dim, dim), dtype=np.uint8)
    main_func = MAIN_FUNCS[args.method]
    with wandb.init(project='slow-artifact-upload-repro') as run:
        main_func(run=run, make_image=make_image, n_images=args.num_images)

if __name__ == '__main__':
    main(parser.parse_args())
