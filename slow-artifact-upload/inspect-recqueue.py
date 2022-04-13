# usage: python inspect-recqueue.py
#     or python -i inspect-recqueue.py
#        to drop into an interpreter, so you can inspect the queues or whatever

'''
Output looks like:

    {"hostname": "anni-load-test", "image_kb": 200, "queue_cap_size": 1000.0}
    {"elapsed": 1.0137245655059814, "queue_size": null, "mem_used": 99049472, "last_1_time": 0.032308101654052734, "last_10_time": 0.31889891624450684, "last_100_time": null}
    {"elapsed": 2.0143213272094727, "queue_size": null, "mem_used": 109330432, "last_1_time": 0.0510408878326416, "last_10_time": 0.3768928050994873, "last_100_time": null}
    {"elapsed": 3.016040563583374, "queue_size": null, "mem_used": 113860608, "last_1_time": 0.02864813804626465, "last_10_time": 0.391310453414917, "last_100_time": null}
    {"elapsed": 4.01734471321106, "queue_size": null, "mem_used": 116199424, "last_1_time": 0.0632939338684082, "last_10_time": 0.40026187896728516, "last_100_time": null}
    {"elapsed": 5.01965069770813, "queue_size": null, "mem_used": 116420608, "last_1_time": 0.038886070251464844, "last_10_time": 0.3598601818084717, "last_100_time": 3.878277063369751}
    {"elapsed": 6.021618366241455, "queue_size": null, "mem_used": 118767616, "last_1_time": 0.038683176040649414, "last_10_time": 0.4426860809326172, "last_100_time": 4.029480457305908}

Where:
- `elapsed` is the time since the start of the run
- `queue_size` is the size of the suspicious queue full of `Record` protos
- `mem_used` is the current memory usage of this process
- `last_{n}_time` is the time it took to make the last n `run.log` calls

'''

import subprocess
from pathlib import Path
import queue
from typing import List, Optional
import weakref
QUEUES = weakref.WeakSet()
class HorribleQueueHack(queue.Queue):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        QUEUES.add(self)
queue.Queue = HorribleQueueHack

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
parser.add_argument('--queue-cap-size', type=float, default=float('inf'))
parser.add_argument('-o', '--stats-file', type=Path, required=True)
args = parser.parse_args()

dim = int(np.sqrt(args.image_size_kb * 1000))


STEP_TIMES: List[float] = []
REC_QUEUE: Optional[queue.Queue] = None
CUR_STEP: Optional[int] = None

def cap_queue_size():
    global REC_QUEUE
    while True:
        try:
            [REC_QUEUE] = [q for q in QUEUES if q.qsize() > 4 and 'Record' in str(type(q.queue[0]))]
            break
        except ValueError:
            time.sleep(0.1)

    while True:
        if REC_QUEUE.qsize() > args.queue_cap_size:
            REC_QUEUE.get()

threading.Thread(target=cap_queue_size).start()

def print_stats():
    this_process = psutil.Process(os.getpid())
    t0 = time.time()
    with args.stats_file.open('w') as f:
        print(json.dumps({
            'hostname': os.uname().nodename,
            'image_kb': args.image_size_kb,
            'queue_cap_size': args.queue_cap_size,
            'commit_hash': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip(),
            'diff': subprocess.check_output(['git', 'diff', 'HEAD']).decode('utf-8'),
        }), file=f)
        while True:
            time.sleep(1)
            print(json.dumps({
                'elapsed': time.time() - t0,
                'queue_size': REC_QUEUE.qsize() if REC_QUEUE else None,
                'cur_step': CUR_STEP,
                'mem_used': this_process.memory_info().rss,
                'last_1_time': STEP_TIMES[-1]-STEP_TIMES[-2] if len(STEP_TIMES) > 1 else None,
                'last_10_time': STEP_TIMES[-1]-STEP_TIMES[-11] if len(STEP_TIMES)>10 else None,
                'last_100_time': STEP_TIMES[-1]-STEP_TIMES[-101] if len(STEP_TIMES)>100 else None,
            }), file=f)
            f.flush()
threading.Thread(target=print_stats).start()

def main():
    global CUR_STEP
    with wandb.init(project='slow_artifact_upload_0407', settings={'start_method':'thread'}) as run:
        t0 = time.time()
        run.config['image_kb'] = args.image_size_kb
        run.config['hostname'] = os.uname().nodename
        run.config['queue_cap_size'] = args.queue_cap_size
        for step in range(60_000_000):
            CUR_STEP = step
            STEP_TIMES.append(time.time())
            run.log({
                'elapsed': time.time() - t0,
                'queue_size': REC_QUEUE.qsize() if REC_QUEUE else None,
                'step': step,
                'last_1_time': STEP_TIMES[-1]-STEP_TIMES[-2] if len(STEP_TIMES) > 1 else None,
                'last_10_time': STEP_TIMES[-1]-STEP_TIMES[-11] if len(STEP_TIMES)>10 else None,
                'last_100_time': STEP_TIMES[-1]-STEP_TIMES[-101] if len(STEP_TIMES)>100 else None,
                f'image_{step}': wandb.Image(np.random.randint(256, size=(dim, dim), dtype=np.uint8)),
            })
# main()
threading.Thread(target=main).start()
