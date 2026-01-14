# 002 NFS mount sweep and run

Support read only NFS mount for sweep and run.

## Background

In previous task, we already supported NFS mount for artifact.
We also have support for listing runs, but it is not in NFS and
stops at run name.

I want to take a step further to extend the NFS logic to support
sweep and run.

One sweep can have multiple runs.
Each run can have config, summary, metrics, files etc.

My current goal is focusing on metadata (summary, config) and run files.
For example, one script I had on exporting summary metrics from sweep's run is:

```python
def export_sweeps(
    entity: str,
    project_name: str,
    cloud: str,
    sdk_version: str,
):
    wandb.login()
    api = wandb.Api()
    project = api.project(name=project_name, entity=entity)

    # Initialize list to store all run data
    all_runs_data: List[Dict] = []

    sweeps = project.sweeps()
    for sweep in sweeps:
        runs = sweep.runs
        for run in runs:
            # Skip run that is not finished
            if run.state != "finished":
                continue
            # Extract data from run
            run_data = {
                "sweep_name": sweep.name,
                "sweep_id": sweep.id,
                "run_name": run.name,
                "action": run.config.get("action", ""),
                "cloud": run.config.get("cloud", ""),
                "wandb_bucket_type": run.config.get("wandb-bucket-type", ""),
                "sdk": run.config.get("sdk", ""),
                "sdk_version": sdk_version,
                "size": run.config.get("size", ""),
                "speed": run.summary.get("speed", ""),
                "time": run.summary.get("time", ""),
            }
            all_runs_data.append(run_data)

    # Create DataFrame and save to CSV
    df = pd.DataFrame(all_runs_data)
    output_file = f"{cloud}_{sdk_version}_sweep_results.csv"
    df.to_csv(output_file, index=False)
    print(f"Results saved to {output_file}")
```

I want to be able to layout sweep and run's metadata as json file(s).
For example, a run could be like: (feel free to change it base on the actual schema of wandb api)

```
runs/
   run-abc
     metadata.json
     files/
       a.python
       b.png
```

For sweep, its runs are actually similar to how we handling collections in artifacts under types.
Each sweep's runs can be softlink to runs

```
sweeps/
   sweep-abc
     runs/
       run-abc -> ../../runs/run-abc
       run-def -> ../../runs/run-def
       ...
```

## Instructions for claude code

- Look at previous task docs to see what and how we did the NFS logic for artifact
- Read SDK code to understand what graphql query you need to add

Trial run

```bash
go build -o wandb-core ./cmd/wandb-core
./wandb-core nfs serve reg-team-2/pinglei-benchmark

mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount
umount /tmp/wandb-mount
```

Bugs

- [x] cannot cd into softlink folder, got `cd: no such file or directory`, softlink's path is wrong
- [x] cat `runs/run-abc/metadata.json` get empty file in first try, second one returns data, size returned 0 for generated metadata.json file

Running tree command actually helps

```text
23:12 $ /tmp/wandb-mount tree -L 4
.
├── artifacts
│   ├── collections
│   │   ├── Qwen-Qwen3-VL-2B-Instruct-20260113-2137
│   │   │   └── v0
│   │   ├── run-jhidltab-history
│   │   │   └── v0
│   │   └── run-unmgo349-history
│   │       └── v0
│   └── types
│       ├── model
│       │   └── Qwen-Qwen3-VL-2B-Instruct-20260113-2137 -> ../../collections/Qwen-Qwen3-VL-2B-Instruct-20260113-2137
│       └── wandb-history
│           ├── run-jhidltab-history -> ../../collections/run-jhidltab-history
│           └── run-unmgo349-history -> ../../collections/run-unmgo349-history
├── runs
│   ├── 6tmybr0b
│   │   ├── files
│   │   │   ├── config.yaml
│   │   │   ├── output.log
│   │   │   ├── requirements.txt
│   │   │   ├── wandb-metadata.json
│   │   │   └── wandb-summary.json
│   │   └── metadata.json
│   ├── 7rl5on12
│   │   ├── files
│   │   │   ├── config.yaml
│   │   │   ├── output.log
│   │   │   ├── requirements.txt
│   │   │   ├── wandb-metadata.json
│   │   │   └── wandb-summary.json
│   │   └── metadata.json
│   ├── dqdy0l20
│   │   ├── files
│   │   └── metadata.json
│   ├── e65x1y5y
│   │   ├── files
│   │   │   ├── config.yaml
│   │   │   ├── output.log
│   │   │   ├── requirements.txt
│   │   │   ├── wandb-metadata.json
│   │   │   └── wandb-summary.json
│   │   └── metadata.json
│   ├── jhidltab
│   │   ├── files
│   │   │   ├── config.yaml
│   │   │   ├── output.log
│   │   │   ├── requirements.txt
│   │   │   ├── wandb-metadata.json
│   │   │   └── wandb-summary.json
│   │   └── metadata.json
│   ├── kdg3psoa
│   │   ├── files
│   │   │   ├── config.yaml
│   │   │   ├── output.log
│   │   │   ├── requirements.txt
│   │   │   ├── wandb-metadata.json
│   │   │   └── wandb-summary.json
│   │   └── metadata.json
│   ├── m9rim0rp
│   │   ├── files
│   │   └── metadata.json
│   └── unmgo349
│       ├── files
│       │   ├── config.yaml
│       │   ├── output.log
│       │   ├── requirements.txt
│       │   ├── wandb-metadata.json
│       │   └── wandb-summary.json
│       └── metadata.json
└── sweeps
    ├── 0sgfnkfx
    │   └── runs
    │       └── 6tmybr0b -> ../../runs/6tmybr0b
    ├── 3dzd7qlq
    │   └── runs
    │       └── unmgo349 -> ../../runs/unmgo349
    ├── 726udfck
    │   └── runs
    │       └── jhidltab -> ../../runs/jhidltab
    ├── atxsgh61
    │   └── runs
    │       └── 7rl5on12 -> ../../runs/7rl5on12
    ├── az6jqovv
    │   └── runs
    │       └── m9rim0rp -> ../../runs/m9rim0rp
    ├── fqkru8w0
    │   └── runs
    │       └── dqdy0l20 -> ../../runs/dqdy0l20
    ├── jyiolwdy
    │   └── runs
    │       └── e65x1y5y -> ../../runs/e65x1y5y
    └── zxgvi5ia
        └── runs
            └── kdg3psoa -> ../../runs/kdg3psoa

49 directories, 46 files
```

Remaining issues

- [ ] sweep does not have `metadata.json`
- [ ] not metrics data, though I am not sure how we should express them, as csv file or just soft link to parquet file if exists? We can also render a image and let claude code to read the image