import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description="Try to reproduce Motorola's slow upload issues")
parser.add_argument("--n-images", type=int, nargs='+', required=True)
parser.add_argument("--image-kb", type=float, nargs='+', required=True)
parser.add_argument("--double-log", choices={True, False}, type=lambda s: {str(b):b for b in [True,False]}[s], nargs='+', required=True)
parser.add_argument("--all-in-memory-at-once-threshold-kb", type=float, default=0, help="passes --all-in-memory-at-once if total size is below this threshold")
parser.add_argument("--random-seed", type=int, default=int(time.time()))
args = parser.parse_args()

HERE = Path(__file__).parent.resolve()

for nimg in args.n_images:
    for kb in args.image_kb:
        for double_log in args.double_log:
            for all_in_memory_at_once in ([True, False] if nimg*kb < args.all_in_memory_at_once_threshold_kb else [False]):
                cmd = [
                    "python3",
                    f"{HERE}/images-in-table-in-artifact.py",
                    f"--n-images={nimg}",
                    f"--image-kb={kb}",
                    *(["--double-log"] if double_log else []),
                    *(["--all-in-memory-at-once"] if all_in_memory_at_once else []),
                    f"--random-seed={args.random_seed}",
                ]
                dir = Path('runs') / f'nimg={nimg}_kb={kb}_dl={double_log}_allmem={all_in_memory_at_once}_seed={args.random_seed}'
                dir.mkdir(parents=True)
                print(f"Running: {' '.join(cmd)}")
                subprocess.check_call(cmd, cwd=dir)
                print('Done')

                with open('runs.jsons', 'a') as f:
                    f.write(json.dumps({'cmd': ' '.join(cmd), 'dir': str(dir)}) + '\n')
