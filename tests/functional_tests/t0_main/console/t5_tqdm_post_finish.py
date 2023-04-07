import wandb
from tqdm.auto import tqdm

run = wandb.init()
progress_bar = tqdm(range(5))
progress_bar.update(1)
run.finish()
progress_bar.update(1)
