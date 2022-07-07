#!/usr/bin/env wandb service --shell

wandb init

for value in `seq 10`; do
  wandb log --key data --value $value
done

wandb finish
