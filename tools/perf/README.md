# Wandb Performance Testing

This is an experimental performance test setup for [Weights & Biases](https://wandb.ai/)'s SDK.

All the performance tests and setup files for the SDK are inside this experimental folder.  You will first build the docker image, start the container, then run perf tests from within the container.

## Setting up a perf container
1. Go to your wandb repo
2. Go to tools/perf
3. Build the docker image
   docker build -t image_name .
5. Start a container
   docker run -d image_name
6. Log into the container
   docker exec -it container_id /bin/bash

## Starting a load test
Once you are logged into your container
1. Set the env variables
   export WANDB_API_KEY=<your key>
   export WANDB_BASE_URL=<your W&B server URL>
2. cd /opt/ns
3. export PYTHONPATH=$(pwd)
4. python -m scripts.run_load_tests -t log_scalar
5. The test results are saved locally on the same directory

## Pushing performance test results and metrics to W&B
After you have a test run, you can optional push the results to W&B for easier visualization
1. python -m scripts.push_perf_results_helper -f test_result_directory -n some_meaningful_test_name -p your_wandb_project_name
