import argparse
import dataclasses
import glob
from importlib.metadata import files
import itertools
from pathlib import Path
import time
from typing import MutableSequence
import wandb

parser = argparse.ArgumentParser(description="Try to reproduce Motorola's slow upload issues")
parser.add_argument("n", type=int, help="number of images to upload")
parser.add_argument("dir", type=Path, help="directory to upload images from")
parser.add_argument("--profile-output", type=Path, default=Path('run.profile'), help="directory to upload images from")

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

    n: int = args.n
    dir: Path = args.dir
    if not dir.is_dir():
        raise ValueError(f"{dir} is not a directory")
    profile_output: Path = args.profile_output

    import cProfile
    profile = cProfile.Profile()
    profile.enable()

    timer = Timer()
    with wandb.init(project="slow-uploads"):

        print(f'Starting run took {timer.tick()}s')
        table = wandb.Table(["Image"])
        files_to_upload = list(itertools.islice(dir.iterdir(), n))
        if len(files_to_upload) != n:
            raise ValueError(f"wanted {n} images, but only found {len(files_to_upload)} in {dir}")
        for f in files_to_upload:
            table.add_data(wandb.Image(str(f)))
        print(f'Adding dir to table took {timer.tick()}s')

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
