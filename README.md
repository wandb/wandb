# Startup time charts

Charts for the `import wandb` and `wandb` CLI startup time investigation (October 2026). They are referenced from the pull request stack https://github.com/wandb/wandb/pull/13144 to https://github.com/wandb/wandb/pull/13150 and are kept on this branch so the pull request descriptions can embed them.

Median of 15 runs per release, one isolated venv per release, Python 3.13, Linux x86_64, warm bytecode cache. HEAD is main at 0.30.1.dev1; "HEAD + stack" is the five PRs, from a paired rerun against main.
