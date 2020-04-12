#!/usr/bin/env python

import wandb

a = wandb.Api()

# preload one of the sweeps
print(a.sweep('adrianbg/wandb-client-standalone_tests/1qycxjnr').config)
#print(a.run('adrianbg/wandb-client-standalone_tests/uyarur2g').sweep_name)
#print(a.run('adrianbg/wandb-client-standalone_tests/s2wssegw').sweep_name)

#print(a.sweep('adrianbg/wandb-client-standalone_tests/x1taizmc'))
#print(a.run('adrianbg/wandb-client-standalone_tests/2bkxvgjb').sweep_name)
#print(a.run('adrianbg/wandb-client-standalone_tests/fmj2fd9g').sweep_name)
#print(a.run('adrianbg/wandb-client-standalone_tests/0d4ifus3').sweep_name)
#print(a.run('adrianbg/wandb-client-standalone_tests/bg1vrdlk').sweep_name)

ids = ['uyarur2g', 's2wssegw'] + ['2bkxvgjb', 'fmj2fd9g', '0d4ifus3', 'bg1vrdlk'] + ['gvzxv5x2']

print([r.sweep_name for r in a.runs('adrianbg/wandb-client-standalone_tests', {'$or': [{'name': i} for i in ids]})])
