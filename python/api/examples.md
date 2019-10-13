---
description: Things you might want to do with our API
---

# Examples

### Read Metrics from a Run

This example outputs timestamp and accuracy saved with `wandb.log({"accuracy": acc})` for a run saved to `<entity>/<project>/<run_id>`.

```python
import wandb
api = wandb.Api()

run = api.run("<entity>/<project>/<run_id>")
if run.state == "finished":
   for k in run.history():
       print(k["_timestamp"], k["accuracy"]) 
```

### Update Metrics in a Run

This example sets the accuracy of a previous run to 0.9. It also modifies the accuracy histogram of a previous run to be the histogram of numpy\_arry

```python
import wandb
api = wandb.Api()

run = api.run("<entity>/<project>/<run_id>")
run.summary["accuracy"] = 0.9
run.summary["accuracy_histogram"] = wandb.Histogram(numpy_array)
run.summary.update()
```

### Export metrics from a single run to a csv file

This script finds all the metrics saved for a single run and saves them to a csv

```python
import wandb
api = wandb.Api()

# run is specified by <entity>/<project>/<run id>
run = api.run("oreilly-class/cifar/uxte44z7")

# save the metrics for the run to a csv file
metrics_dataframe = run.history()
metrics_dataframe.to_csv("metrics.csv")
```

### Export metrics from all runs in a project to a csv file

This script finds a project and outputs a CSV of runs with name, configs and summary stats.

```python
import wandb
api - wandb.Api()

# Change oreilly-class/cifar to <entity/project-name>
runs = api.runs("oreilly-class/cifar")
summary_list = [] 
config_list = [] 
name_list = [] 
for run in runs: 
    # run.summary are the output key/values like accuracy.  We call ._json_dict to omit large files 
    summary_list.append(run.summary._json_dict) 

    # run.config is the input metrics.  We remove special values that start with _.
    config_list.append({k:v for k,v in run.config.items() if not k.startswith('_')}) 
    
    # run.name is the name of the run.
    name_list.append(run.name)       

import pandas as pd 
summary_df = pd.DataFrame.from_records(summary_list) 
config_df = pd.DataFrame.from_records(config_list) 
name_df = pd.DataFrame({'name': name_list}) 
all_df = pd.concat([name_df, config_df,summary_df], axis=1)

all_df.to_csv("project.csv")

```

