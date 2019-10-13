# Overview

### What is wandb?

Our product, wandb, is an experiment tracking tool for machine learning practitioners. We want to make it easy for anyone doing machine learning to keep track of all of their experiments and share their results with colleagues and their future self.

Here's a 1 minute overview video.

{% embed url="https://www.youtube.com/watch?v=icy3XkZ5jBk" %}

### How does it work?

When you instrument your training code with wandb, as you train your models our background process will collect useful data about what is happening. For example, we can keep track of model performance metrics, hyperparameters, gradients, system metrics, model files, your most recent git commit to help you keep track of exactly how you trained your models.

{% page-ref page="../python/api/examples.md" %}

### How hard is it to setup?

We know that most people are tracking their training in things like emacs and Google Sheets, so we've designed wandb to be as lightweight as possible. Integration should take 5-10 minutes, and wandb won't hurt performance or crash your training script.

## Benefits of wandb

Our users tell us that they get three kinds of benefits from using wandb:

### 1. Visualizing training

Some of our users think of wandb as a "persistent TensorBoard". For individual runs, we collect model performance metrics like accuracy and loss. If you want us to, we also collect and display system metrics, matplotlib object, model files, your most recent git commit SHA + a patch file of any changes since your last commit.

You can also take notes about individual runs and they will be saved along with your training data. Here's an [example project](https://app.wandb.ai/bloomberg-class/imdb-classifier/runs/2tc2fm99/overview) where we taught a class to Bloomberg.

### 2. Organize and compare lots of training runs

Most people training machine learning models are trying lots and lots of versions of their model and our goal is to help people stay organized.

You can create projects to keep all of your runs in a single place. You can visualize performance metrics across lots of runs and filter, group and tag them any way you like.

A good public example of a project is our friend Bingbin's [crossing project](https://app.wandb.ai/bingbin/crossing?workspace=user-l2k2). She ran and tagged a few hundred runs. If you click on the icon next to the word "Runs" it will expand her table of runs. You can sort by accuracy, loss or anything else.

### 3. Share your results

Once you have done lots of runs you usually want to organize them to show some kind of result. Our friends at Latent Space wrote a nice article called [ML Best Practices: Test Driven Development](https://www.wandb.com/articles/ml-best-practices-test-driven-development) that talks about how they use W&B reports to improve their teams productivity.

A user Boris Dayma wrote a public example report on a project he did on [Semantic Segmentation](https://app.wandb.ai/borisd13/semantic-segmentation/reports?view=borisd13%2FSemantic%20Segmentation%20Report). He walks through various approaches he tried and how well they work.

We really hope that wandb encourages ML teams to collaborate more productively.

If you are interested in understanding more about how other teams use wandb we've recorded interviews with our technical users at [OpenAI](https://www.wandb.com/articles/why-experiment-tracking-is-crucial-to-openai) and [Toyota Research](https://www.youtube.com/watch?v=CaQCw-DKiO8).

