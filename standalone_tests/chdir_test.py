import wandb
import os

# test to ensure
run = wandb.init(project='chdir_media_test', entity='kylegoyette')
try:
    os.makedirs('./chdir_test')
except Exception as e:
    print(e)
os.chdir('./chdir_test')
# log some table data, which is saved in the media folder
pr_data = [
    ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0],
    ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0], ['setosa', 1.0, 1.0],
    ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0],
    ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0], ['setosa', 1.0, 0.0],
    ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0],
    ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0],
    ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 1.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0],
    ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0],
    ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0], ['versicolor', 1.0, 0.0]
    ]
# convert the data to a table
pr_table = wandb.Table(data=pr_data, columns=["class", "precision", "recall"])
wandb.log({'pr_table': pr_table})
files = os.listdir(run.dir)
# check that the media folder exists in the run dir
assert 'media' in files
