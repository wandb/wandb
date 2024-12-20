# Wandb Performance Testing

This is an experimental performance test setup for [Weights & Biases](https://wandb.ai/)'s SDK.

All the performance tests and setup files for the SDK are inside this experimental folder.  You will first build the docker image, start the container, then run perf tests from within the container.

## Setting up a perf container
1. Go to your wandb repo
2. Go to experimental/perf
3. Build the docker image
   docker build -t perfimage .
4. Start a container
   docker run perfimage
5. Log into the container
   docker ssh exec -it container_id /bin/bash

## Starting a load test
Once you are logged into your container
1. Set the env variables
   export WANDB_API_KEY=<your key>
   export WANDB_BASE_URL=<your W&B server URL>
2. cd /opt/ns
3. python -m scripts.run_load_test -t log_scalar
4. The test results are saved locally on the same directory

## Pushing performance test results and metrics to W&B
After you have a test run, you can optional push the results to W&B for easier visualization
1. python -m scripts.push_perf_results_helper -f test_result_directory -n some_meaningful_test_name -p your_wandb_project_name
