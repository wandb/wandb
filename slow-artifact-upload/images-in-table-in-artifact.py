import argparse
import dataclasses
import glob
from pathlib import Path
import time
from typing import MutableSequence
import wandb

parser = argparse.ArgumentParser(description="Upload files to wandb")
parser.add_argument("dir", type=Path, help="Directory to upload")

@dataclasses.dataclass
class Timer:

    tick_times: MutableSequence[float] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        self.tick_times.append(time.time())

    @property
    def total(self) -> float:
        return self.tick_times[-1] - self.tick_times[0]

    def tick(self, now: float) -> float:
        '''Update the last-tick-time and return the time elapsed since.'''
        self.tick_times.append(now)
        return now - self.tick_times[-2]

def main(args):

    dir: Path = args.dir
    if not dir.is_dir():
        raise ValueError(f"{dir} is not a directory")

    timer = Timer()
    with wandb.init(project="slow-uploads"):


        table = wandb.Table(["Image"])
        for img in glob.glob(str(dir) + "/*"):
            table.add_data(wandb.Image(img))
        print(f'Adding dir to table took {timer.tick(time.time())}s')

        art = wandb.Artifact('rand_small', 'dataset')
        art.add(table, 'table')
        t2 = time.time()
        print(f'Adding table to artifact took {timer.tick(time.time())}s')
        art.save()
        t3 = time.time()
        print(f'Saving artifact took {timer.tick(time.time())}s')

    print(f'Finishing run took {timer.tick(time.time())}s')
    print(f'Total time: {timer.total}s')


if __name__ == "__main__":
    main(parser.parse_args())
