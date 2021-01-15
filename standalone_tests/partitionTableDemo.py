import ray
import wandb
import numpy as np

project = "dist_dev_test"
table_name = "dataset_demo"
table_parts_dir = "dataset_parts"
artifact_name = "dist_dataset_demo"
group_name = "test_group_{}".format(np.random.rand())
artifact_type = "dataset"
columns = ["A", "B", "C"]
data = []

# Start Ray.
ray.init()

@ray.remote
def train(i):
    run = wandb.init(project=project, group=group_name)
    artifact = wandb.Artifact(artifact_name, type=artifact_type)
    row = [i,i*i,2**i]
    table = wandb.Table(columns=columns, data=[row])
    artifact.add(table, "{}/{}".format(table_parts_dir, i))
    run.upsert_artifact(artifact)
    run.finish()

# Start 4 tasks in parallel.
result_ids = []
for i in range(4):
    result_ids.append(train.remote(i))
    
# Wait for the tasks to complete and retrieve the results.
# With at least 4 cores, this will take 1 second.
results = ray.get(result_ids)  # [0, 1, 2, 3]

run = wandb.init(project=project, group=group_name)
artifact = wandb.Artifact(artifact_name, type=artifact_type)
partition_table = wandb.data_types.PartitionedTable(parts_path=table_parts_dir)
artifact.add(partition_table, table_name)
run.finish_artifact(artifact)
run.finish()