---
description: 'Track machine learning experiments, visualize metrics, and share results'
---

# Weights & Biases

Weights & Biases helps you keep track of your machine learning experiments. Use our tool to log hyperparameters and output metrics from your runs, then visualize and compare results and quickly share findings with your colleagues.

![](.gitbook/assets/image%20%281%29.png)

Here's a sample screenshot from a [Species Identification project](https://app.wandb.ai/stacey/curr_learn/reports?view=stacey%2FSpecies%20Identification) in W&B.

## Getting Started

Easily add our package, `wandb`, to your model script.

* [Quickstart](quickstart.md)
* [Keras integration](python/frameworks/keras.md)
* [PyTorch integration](python/frameworks/pytorch.md)
* [TensorFlow integration](python/frameworks/tensorflow.md)

## Examples

If you're interested in example projects, we have a few resources:

* [App Gallery](https://app.wandb.ai/gallery): A gallery of featured reports in our web app
* [Example Projects](python/example-projects/): Python scripts and the results in our web app

## Common Questions

### How do I pronounce "wandb"?

You can pronounce it w-and-b \(as we originally intended\), wand-b \(because it's magic like a wand\), or wan-db \(because it saves things like a database\).

### How much does this thing cost?

W&B is free for personal and academic projects. We are committed to staying free for academic and open source projects and making it easy to export data.

If you want to host private projects for a company, email us at [contact@wandb.com](mailto:contact@wandb.com).

### Do you offer an on-premises version of your software?

Yes! If you're interested, reach out to us at [contact@wandb.com](mailto:contact@wandb.com).

### How is this different than TensorBoard?

W&B is a distributed cloud hosted solution so your results are saved forever and it's still snappy after 1000's of runs have been monitored. We offer additional features such as system metrics, commit history, experiment notes, dashboards, and advanced searching / aggregation across runs and projects.

### Who has rights to the data?

You can always export and delete your data at any time. We will never share data associated with private projects. We hope that when you can, you will make your work public so that other practitioners can learn from it.

We hope to discover and share high level patterns to move the field of machine learning forward. For example, we wrote [this article](https://www.wandb.com/articles/monitor-improve-gpu-usage-for-model-training) on how people are not fully utilizing their GPUs. We want to do this in a way that respects your privacy and feels honest. If you have any concerns about data privacy, we'd love to hear from you. Reach out at contact@wandb.com.

### Can I just log metrics, no code or dataset examples?

**Dataset Examples**

By default, we don't log any of your dataset examples. You can explicitly turn this feature on to see example predictions in our web interface.

**Code Logging**

There's two ways to turn off code logging:

1. Set **WANDB\_DISABLE\_CODE** to **true** to turn off all code tracking. We won't pick up the git SHA or the diff patch.
2. Set **WANDB\_IGNORE\_GLOBS** to **\*.patch** to turn off syncing the diff patch to our servers. You'll still have it locally and be able to apply it with the [wandb restore](python/using-the-cli.md#restore-the-state-of-your-code) command.

