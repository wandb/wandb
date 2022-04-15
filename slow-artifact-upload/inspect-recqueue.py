# usage: python inspect-recqueue.py
#     or python -i inspect-recqueue.py
#        to drop into an interpreter, so you can inspect the queues or whatever

'''
Output looks like:

    {"hostname": "anni-load-test", "image_kb": 200}
    {"elapsed": 1.0137245655059814, "mem_used": 99049472, "last_1_time": 0.032308101654052734, "last_10_time": 0.31889891624450684, "last_100_time": null}
    {"elapsed": 2.0143213272094727, "mem_used": 109330432, "last_1_time": 0.0510408878326416, "last_10_time": 0.3768928050994873, "last_100_time": null}
    {"elapsed": 3.016040563583374, "mem_used": 113860608, "last_1_time": 0.02864813804626465, "last_10_time": 0.391310453414917, "last_100_time": null}
    {"elapsed": 4.01734471321106, "mem_used": 116199424, "last_1_time": 0.0632939338684082, "last_10_time": 0.40026187896728516, "last_100_time": null}
    {"elapsed": 5.01965069770813, "mem_used": 116420608, "last_1_time": 0.038886070251464844, "last_10_time": 0.3598601818084717, "last_100_time": 3.878277063369751}
    {"elapsed": 6.021618366241455, "mem_used": 118767616, "last_1_time": 0.038683176040649414, "last_10_time": 0.4426860809326172, "last_100_time": 4.029480457305908}

Where:
- `elapsed` is the time since the start of the run
- `queue_size` is the size of the suspicious queue full of `Record` protos
- `mem_used` is the current memory usage of this process
- `last_{n}_time` is the time it took to make the last n `run.log` calls

'''

import subprocess
from pathlib import Path
from typing import List, Optional
import json
import os
import psutil
import threading
import time
import numpy as np
import wandb

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-s', '--image-size-kb', type=int, required=True)
parser.add_argument('-o', '--stats-file', type=Path, required=True)
args = parser.parse_args()

dim = int(np.sqrt(args.image_size_kb * 1000))


STEP_TIMES: List[float] = []
CUR_STEP: Optional[int] = None
BACKEND_PROCESS = None

def print_stats():
    t0 = time.time()
    with args.stats_file.open('w') as f:
        print(json.dumps({
            'hostname': os.uname().nodename,
            'image_kb': args.image_size_kb,
            'commit_hash': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip(),
            'diff': subprocess.check_output(['git', 'diff', 'HEAD']).decode('utf-8'),
        }), file=f)
        while True:
            time.sleep(1)
            print(json.dumps({
                'elapsed': time.time() - t0,
                'cur_step': CUR_STEP,
                'mem_used': BACKEND_PROCESS.memory_info().rss if BACKEND_PROCESS else None,
                'last_1_time': STEP_TIMES[-1]-STEP_TIMES[-2] if len(STEP_TIMES) > 1 else None,
                'last_10_time': STEP_TIMES[-1]-STEP_TIMES[-11] if len(STEP_TIMES)>10 else None,
                'last_100_time': STEP_TIMES[-1]-STEP_TIMES[-101] if len(STEP_TIMES)>100 else None,
            }), file=f)
            f.flush()
threading.Thread(target=print_stats).start()

def main():
    global CUR_STEP
    with wandb.init(project='slow_artifact_upload_0407') as run:
        global BACKEND_PROCESS
        BACKEND_PROCESS = psutil.Process(run._backend.wandb_process.pid)
        for step in range(60_000_000):
            CUR_STEP = step
            STEP_TIMES.append(time.time())
            run.log({
                f'image_{step}': wandb.Image(np.random.randint(256, size=(dim, dim), dtype=np.uint8)),
            })
# main()
threading.Thread(target=main).start()
