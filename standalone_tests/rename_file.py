import os
import time
import wandb

wandb.init()

path = os.path.join(wandb.run.dir, 'a.txt')
f = open(path, 'w')
f.write('contents!')
f.close()

time.sleep(3)

os.rename(path, os.path.join(wandb.run.dir, 'b.txt'))

time.sleep(1)