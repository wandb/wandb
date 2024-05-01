# wandb benchmark testing

## Overview

The wandb SDK is designed to be a flexible, performant and robust library which can be integrated into data projects with limited overhead.  The design presents some trade-offs which can appear as unexpected performance characteristics.   This benchmark test suite will cover some common usage profiles and capture the user perceived characteristics.

The wandb SDK architecture consists of 
1) a user-process frontend library
2) an internally managed process which is responsible for processing and syncing data 

The SDK is in the middle of a transition to a new internally managed process (core) which provides improved performance as well as laying the groundwork for many more improvements to come.   This is described here:
[wandb core](https://github.com/wandb/wandb/blob/main/core/README.md)

## Tests

### 

## Results

### Raw results
```
v1-2024-04-11-0,,v1-empty,"mode=offline,core=false",,,,,time_load,1.9792468547821045
v1-2024-04-11-0,,v1-empty,"mode=offline,core=true",,,,,time_load,1.5073113441467285
v1-2024-04-11-0,,v1-empty,"mode=online,core=false",,,,,time_load,2.9091131687164307
v1-2024-04-11-0,,v1-empty,"mode=online,core=true",,,,,time_load,1.8496718406677246
v1-2024-04-11-0,,v1-scalers,"mode=offline,core=false",,,,,time_load,10.043172836303711
v1-2024-04-11-0,,v1-scalers,"mode=offline,core=true",,,,,time_load,1.6653656959533691
v1-2024-04-11-0,,v1-scalers,"mode=online,core=false",,,,,time_load,16.66104531288147
v1-2024-04-11-0,,v1-scalers,"mode=online,core=true",,,,,time_load,1.9638187885284424
v1-2024-04-11-0,,v1-tables,"mode=offline,core=false",,,,,time_load,4.849104166030884
v1-2024-04-11-0,,v1-tables,"mode=offline,core=true",,,,,time_load,3.985367774963379
v1-2024-04-11-0,,v1-tables,"mode=online,core=false",,,,,time_load,26.990600109100342
v1-2024-04-11-0,,v1-tables,"mode=online,core=true",,,,,time_load,16.211838960647583
```
