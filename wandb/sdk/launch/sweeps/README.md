# Schedulers

Hyperparameter optimization. Currently two backends are supported:

- `OptunaScheduler` - scheduler that uses the Optuna HPO library
- `SweepsScheduler` - the original wandb sweeps scheduler


Feature | Classic Sweeps | Optuna
:------------ | :-------------| :-------------|
Conditional Configuration |   | :white_check_mark:
Grid Search | :white_check_mark: | :white_check_mark:
Random Search | :white_check_mark: | :white_check_mark:
Bayes Search | :white_check_mark: | :white_check_mark:
TPE (Tree-structured Parzen Estimator) |   | :white_check_mark:
CMA-ES (Covariance matrix adaptation evolution strategy) |   | :white_check_mark:
Asynchronous Successive Halving |   | :white_check_mark:
Hyperband  | :white_check_mark: | :white_check_mark:
Median pruning  |   | :white_check_mark:
Threshold pruning |   | :white_check_mark: