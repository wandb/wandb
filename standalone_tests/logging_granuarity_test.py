#!/usr/bin/env python

import time
import random

import wandb

wandb.init()

for i in range(3):
	for j in range(10):
		loss = random.random()
		wandb.run.history.add({'mb-loss': loss, 'loss': loss, 'mb': j, 'ep': i})
		time.sleep(1)
	loss = random.random()
	wandb.run.history.add({'ep-loss': loss, 'loss': loss, 'ep': i})
	time.sleep(1)
