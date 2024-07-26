# wandb benchmark testing

## Overview

The wandb SDK is designed to be a flexible, performant and robust library which can be integrated into data projects with limited overhead.  The design presents some trade-offs which can appear as unexpected performance characteristics.   This benchmark test suite will cover some common usage profiles and capture the user perceived characteristics.

The wandb SDK architecture consists of
1) a user-process frontend library
2) an internally managed backend process which is responsible for processing and syncing data

This suite of benchmarks can serve as a mechanism to:
- Track ongoing performance of high level SDK features to help spot regressions
- Demonstrate performance improvements and trade-offs when enabling SDK features

The SDK is in the middle of a transition to a new internally managed backend process (also called "core") which provides improved performance as well as laying the groundwork for many more improvements to come.   This is project is described here:
[wandb core](https://github.com/wandb/wandb/blob/main/core/README.md).

## Tests

### Startup/Shutdown Performance

When initiating an experiment there is a setup cost to make sure the experiment is reliably tracked.  The delays in starting and stopping an experiment is SDK overhead which takes away from compute resources which could be used for model training.  This overhead is mostly noticed with very short experiments (measured in seconds).

This is best understood with a simple script:
```python
run = wandb.init()
# ... perform model training
run.finish()
```

### Parallel Run Performance

The SDK has the ability to track multiple experiments in parallel for example using python multiprocessing

```python
import multiprocessing


def run_experiment():
    # do work
    pass


p = multiprocessing.Process(target=run_experiment)
```

### Logging tables

Wandb tables are an important datatype that allows detailed analysis in the wandb UI.

Example of table usage:

```python
run.log({"table1": wandb.Table(columns=..., data=...)})
```

## Results

### Methodology

The wandb SDK supports online and offline modes of operation.  Offline logging allows the customer
to decouple running experiments from syncing the data to the backend server.

Each test is defined as a profile is parameterized with a load specification.  See `_load_profiles.py` for more details.

### Improvements enabling wandb core

#### Benchmark results

| Metric | Mode | Improvement with wandb core |
| --- | --- | --- |
| Startup/Shutdown Time | Offline | 36% improvement |
| Startup/Shutdown Time | Online | 23% improvement |
| Parallel scalar logging performance | Offline | 83% improvement |
| Parallel scalar logging performance | Online | 88% improvement |
| Table logging performance | Offline | 18% improvement |
| Table logging performance | Online | 40% improvement |

### System robustness

The wandb core project replaces a python process with a process that is written in golang.  The golang
process is statically linked and provides better isolation from the customers python environment.  This will
be most evident in customer environments where the python environment either bespoke in some ways (using alternate python packaging mechanisms - PEX etc), or if it is served from lower shared filesystems that could have less predictable performance characteristics.

<details>
<summary>Raw Results</summary>

```bash
for p in v1-empty v1-scalars v1-tables; do
  ./bench.py --test_profile "$p"
done
```

results.csv:
```
v1-2024-04-11-0,,v1-empty,"mode=offline,core=false",,,,,time_load,1.9792468547821045
v1-2024-04-11-0,,v1-empty,"mode=offline,core=true",,,,,time_load,1.5073113441467285
v1-2024-04-11-0,,v1-empty,"mode=online,core=false",,,,,time_load,2.9091131687164307
v1-2024-04-11-0,,v1-empty,"mode=online,core=true",,,,,time_load,1.8496718406677246
v1-2024-04-11-0,,v1-scalars,"mode=offline,core=false",,,,,time_load,10.043172836303711
v1-2024-04-11-0,,v1-scalars,"mode=offline,core=true",,,,,time_load,1.6653656959533691
v1-2024-04-11-0,,v1-scalars,"mode=online,core=false",,,,,time_load,16.66104531288147
v1-2024-04-11-0,,v1-scalars,"mode=online,core=true",,,,,time_load,1.9638187885284424
v1-2024-04-11-0,,v1-tables,"mode=offline,core=false",,,,,time_load,4.849104166030884
v1-2024-04-11-0,,v1-tables,"mode=offline,core=true",,,,,time_load,3.985367774963379
v1-2024-04-11-0,,v1-tables,"mode=online,core=false",,,,,time_load,26.990600109100342
v1-2024-04-11-0,,v1-tables,"mode=online,core=true",,,,,time_load,16.211838960647583
```
</details>
