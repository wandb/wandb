#!/usr/bin/env python

import time

import wandb

def train():
	wandb.init()
	time.sleep(10)

sweep_id = wandb.sweep(dict(method='random', parameters=dict(lr=dict(min=0.01, max=0.10))))

wandb.agent(sweep_id, function=train)
