# Jupyter

### Jupyter Integration

**wandb** integrates with Jupyter notebooks. Any time `wandb.init()` is called a new run will be created and a url displayed. If the machine or directory you are running `jupyter notebook` from isn't configured, you will be prompted to configure the directory interactively in the notebook.

You can call `wandb.log` as you would normally and metrics will be sent to the run created by `wandb.init()`. If you want to display live results in the notebook, you can decorate the cell that calls `wandb.log` with **%%wandb**. If you run this cell multiple times, data will be appended to the run.

### Colaboratory

**wandb** works great in colab. The first time you call `wandb.init` we will automatically pull in your credentials if you're already logged into wandb.

### Launching Jupyter

Calling `wandb docker --jupyter` will launch a docker container, mount your code in it, ensure jupyter is installed and launch it on port 8888.

### Sharing Notebooks

If your project is private, viewers of your notebook will be prompted to login to view results.

