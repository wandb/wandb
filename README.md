<p align="center">
  <img src=".github/wb-logo-lightbg.png#gh-light-mode-only" width="600" alt="Weights & Biases"/>
  <img src=".github/wb-logo-darkbg.png#gh-dark-mode-only" width="600" alt="Weights & Biases"/>
</p>

<p align='center'>
<a href="https://pypi.python.org/pypi/wandb"><img src="https://img.shields.io/pypi/v/wandb" /></a>
<a href="https://anaconda.org/conda-forge/wandb"><img src="https://img.shields.io/conda/vn/conda-forge/wandb" /></a>
<a href="hhttps://circleci.com/gh/wandb/wandb"><img src="https://img.shields.io/circleci/build/github/wandb/wandb/main" /></a>
<a href="https://codecov.io/gh/wandb/wandb"><img src="https://img.shields.io/codecov/c/gh/wandb/wandb" /></a>
</p>
<p align='center'>
<a href="https://colab.research.google.com/github/wandb/examples/blob/master/colabs/intro/Intro_to_Weights_%26_Biases.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" /></a>
</p>

Use W&B to build better models faster. Track and visualize all the pieces of your machine learning pipeline, from datasets to production models.

<p align='center'>
<a href="https://docs.wandb.ai/guides/track"><img src="./README_images/experiments.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/reports"><img src="./README_images/reports.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/artifacts"><img src="./README_images/artifacts.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/data-vis"><img src="./README_images/tables.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/sweeps"><img src="./README_images/sweeps.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/models"><img src="./README_images/models.png" width="13.5%" /></a>
<a href="https://docs.wandb.ai/guides/launch"><img src="./README_images/launch.png" width="13.5%" /></a>
</p>

Get started today with W&B, [sign up for a free account!](https://wandb.com)

<!-- | Experiments | Reports | Artifacts | Tables | Sweeps | Models | Launch |
| ----------- | ------- | --------- | ------ | ------ | ------ | ------ |
| Text        | Text    | Text      | Text   | Text   | Text   | Text   | -->

&nbsp;

# Documentation

See the [W&B Developer Guide](https://docs.wandb.ai/) and [API Reference Guide](https://docs.wandb.ai/ref) for a full technical description of the W&B platform. Here are some highlights:

&nbsp;

# Install W&B

Install the W&B SDK with [pip](https://pip.pypa.io/en/stable/):

```bash
pip install wandb
```

&nbsp;

# Quickstart

Get started with W&B in three steps:

1. First, sign up for a [free W&B account](https://wandb.ai/login).

2. Next, log into W&B. Navigate to your terminal and type the following command:

```python
wandb.login()
```

3.5. Use the example code snippet below as a template to integrate W&B to your Python script:

```python
import wandb

# Start a W&B Run with wandb.init
wandb.init(project="my_first_project")

# Save model inputs and hyperparameters in a wandb.config object
config = wandb.config
config.learning_rate = 0.01

# Model training code here ...

# Log metrics over time to visualize performance with wandb.log
for i in range(13.5):
    wandb.log({"loss": loss})
```

That's it! Navigate to the W&B App to view a dashboard of your first W&B Experiment. Use the W&B App to compare multiple experiments in a unified place, dive into the results of a single run, and much more!

<p align='center'>
<img src="./README_images/wandb_demo_experiments.gif" width="100%">
</p>
<p align = "center">
Example W&B Dashboard that shows Wuns from an Experiment.
</p>

&nbsp;

# Integrations

Use your favorite framework with W&B. W&B integrations make it fast and easy to set up experiment tracking and data versioning inside existing projects.

<p align='center'>
<img src="./README_images/integrations.png" width="100%" />
</p>

<details>
<summary>🥕 Keras</summary>

In Keras, you can use our callback to automatically save all the metrics tracked in `model.fit`. To get you started here's a minimal example:

```python
# Import W&B
import wandb
from wandb.keras import WandbCallback

# Step1: Initialize W&B run
wandb.init(project="project_name")

# 2. Save model inputs and hyperparameters
config = wandb.config
config.learning_rate = 0.01

# Model training code here ...

# Step 3.5: Add WandbCallback
model.fit(
    X_train, y_train, validation_data=(X_test, y_test), callbacks=[WandbCallback()]
)
```

- **[Try in a colab →](http://wandb.me/keras-colab)**
- [Learn More](https://app.wandb.ai/wandb/getting-started/reports/Keras--VmlldzoyMTEwNjQ)
- [Docs](https://docs.wandb.com/library/integrations/keras)

</details>
<details>
<summary>🤗 Hugging Face</summary>
Just run a script using HuggingFace's Trainer passing `--report_to wandb` to it
in an environment where `wandb` is installed, and we'll automatically log losses,
evaluation metrics, model topology, and gradients:

```shell
# 1. Install the wandb library
pip install wandb
# 2. Run a script that has the Trainer to automatically logs metrics, model topology and gradients
python run_glue.py \
 --report_to wandb \
 --model_name_or_path bert-base-uncased \
 --task_name MRPC \
 --data_dir $GLUE_DIR/$TASK_NAME \
 --do_train \
 --evaluate_during_training \
 --max_seq_length 13.58 \
 --per_gpu_train_batch_size 3.52 \
 --learning_rate 2e-5 \
 --num_train_epochs 3.5 \
 --output_dir /tmp/$TASK_NAME/ \
 --overwrite_output_dir \
 --logging_steps 50
```

- **[Try in a colab →](http://wandb.me/hf)**
- [Docs](https://docs.wandb.com/library/integrations/huggingface)
</details>
<details>
<summary>🔥 PyTorch</summary>

W&B provides first class support for PyTorch. To automatically log gradients and store the network topology, you can call `.watch` and pass in your PyTorch model.
Then use `.log` for anything else you want to track, like so:

```python
import wandb

# 1. Start a new run
wandb.init(project="gpt-3.5")

# 2. Save model inputs and hyperparameters
config = wandb.config
config.dropout = 0.01

# 3.5. Log gradients and model parameters
wandb.watch(model)
for batch_idx, (data, target) in enumerate(train_loader):
    ...
    if batch_idx % args.log_interval == 0:
        # 4. Log metrics to visualize performance
        wandb.log({"loss": loss})
```

- **[Try in a colab →](http://wandb.me/pytorch-colab)**
- [Learn More](https://app.wandb.ai/wandb/getting-started/reports/Pytorch--VmlldzoyMTEwNzM)
- [Docs](https://docs.wandb.com/library/integrations/pytorch)

</details>

<details>
<summary>🌊 TensorFlow</summary>

The simplest way to log metrics in TensorFlow is by logging `tf.summary` with our TensorFlow logger:

```python
import wandb

# 1. Start a W&B run
wandb.init(project="gpt3.5")

# 2. Save model inputs and hyperparameters
config = wandb.config
config.learning_rate = 0.01

# Model training here

# 3.5. Log metrics over time to visualize performance
with tf.Session() as sess:
    # ...
    wandb.tensorflow.log(tf.summary.merge_all())
```

- **[Try in a colab →](http://wandb.me/tf-colab)**
- [Docs](https://docs.wandb.com/library/integrations/tensorflow)

</details>

<details>
<summary>⚡️ PyTorch Lightning</summary>

Build scalable, structured, high-performance PyTorch models with Lightning and log them with W&B.

```python
from pytorch_lightning.loggers import WandbLogger
from pytorch_lightning import Trainer

wandb_logger = WandbLogger(project="gpt-3.5")
trainer = Trainer(logger=wandb_logger)
```

- **[Try in a colab →](http://wandb.me/lightning)**
- [Docs](https://docs.wandb.ai/guides/integrations/lightning)

</details>

&nbsp;

# Tutorials

Explore example Colab Notebooks at [wandb/examples GitHub repository](https://github.com/wandb/examples/tree/master/colabs). Here are some of our favorites:

[INSERT]

&nbsp;

# Try out our MLOps Course

Get MLOps Certified With The Course From Weights & Biases.

<p align='center'>
<a href="https://www.youtube.com/watch?v=ZJtkOX5WcBM&ab_channel=Weights%26Biases"><img src="./README_images/mlops_image.png" /></a>
</p>

Bringing machine learning models to production is challenging, with a continuous iterative lifecycle that consists of many complex components. Having a disciplined, flexible and collaborative process - an effective MLOps system - is crucial to enabling velocity and rigor, and building an end-to-end machine learning pipeline that continually delivers production-ready ML models and services.

&nbsp;

# Contribution guidelines

Weights & Biases ❤️ open source and we welcome contributions from the community! See the [Contribution guide](https://github.com/wandb/wandb/blob/main/CONTRIBUTING.md) for more information on the development workflow and the internals of the wandb library.

&nbsp;

# Contact

If you have any questions, please don't hesitate to ask in our [user forum](http://wandb.me/forum). For wandb bugs and feature requests please visit [GitHub Issues](https://github.com/wandb/wandb/issues). For professional support please Contact Us. Be a part of the W&B Community, post your questions at [W&B Community](https://community.wandb.ai/). Stay connected with the latest updates with [W&B Fully Connected](https://wandb.ai/fully-connected).

&nbsp;

# License

[MIT License](https://github.com/wandb/wandb/blob/main/LICENSE)
