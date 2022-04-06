import argparse
import dataclasses
import glob
from importlib.metadata import files
import itertools
from pathlib import Path
import time
from typing import MutableSequence

import numpy
import wandb

parser = argparse.ArgumentParser(description="Try to reproduce Motorola's slow upload issues")
parser.add_argument("-n", "--n-images", type=float, required=True, help="number of files to upload")
parser.add_argument("-s", "--image-bytes", type=float, required=True, help="approximate size of files to upload, in bytes")
parser.add_argument("--profile-output", type=Path, default=Path('run.profile'))

@dataclasses.dataclass
class Timer:

    tick_times: MutableSequence[float] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        self.tick_times.append(time.time())

    @property
    def total(self) -> float:
        return self.tick_times[-1] - self.tick_times[0]

    def tick(self) -> float:
        '''Update the last-tick-time and return the time elapsed since.'''
        now = time.time()
        self.tick_times.append(now)
        return now - self.tick_times[-2]

def main(args):

    num_images = int(args.n_images)
    approx_image_bytes = int(args.image_bytes)
    profile_output: Path = args.profile_output

    image_width = int(numpy.sqrt(approx_image_bytes / 3))
    mkimg = lambda: numpy.random.random((image_width, image_width, 3))

    import cProfile
    profile = cProfile.Profile()
    profile.enable()

    timer = Timer()
    with wandb.init(project="slow-uploads"):

        print(f'Starting run took {timer.tick()}s')
        table = wandb.Table(["Image"])
        for _ in range(num_images):
            table.add_data(wandb.Image(mkimg()))
        print(f'Creating images and adding them to the table took {timer.tick()}s')

        art = wandb.Artifact('rand_small', 'dataset')
        art.add(table, 'table')
        print(f'Adding table to artifact took {timer.tick()}s')
        art.save()
        print(f'Saving artifact took {timer.tick()}s')

    print(f'Finishing run took {timer.tick()}s')
    print(f'Total time: {timer.total}s')

    profile.disable()
    profile.dump_stats(str(profile_output))


if __name__ == "__main__":
    main(parser.parse_args())
