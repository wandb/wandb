# Sweeps on Launch 🚀 

_Using Launch to run a sweep._

Create the sweep as you would normally, but specify a `queue`. Here we specify the default queue

```
WANDB_BASE_URL=https://api.wandb.test wandb sweep sweep-bayes.yaml --queue my_cool_sweep --entity hupo
```

Within the [Launch UI in your workspace](https://wandb.ai/wandb/launch-welcome/launch) you should now see a launch queue with a scheduler job on it.

Start the Scheduler by pointing a launch agent at the queue:

```
WANDB_BASE_URL=https://api.wandb.test wandb launch-agent -q my_cool_sweep -p sweeps-examples -j -1
```

Within the [Launch UI in your workspace](https://wandb.ai/wandb/launch-welcome/launch) you should now see sweeps jobs on the launch queue, these are being added there by the Scheduler. The launch agent will now work through these jobs.