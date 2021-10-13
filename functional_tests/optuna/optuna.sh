id: 0.optuna
plugin:
    - wandb
command:
    program: test_optuna.py
depend:
    requirements:
        - optuna>=2.10
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][project]: integrations_testing
  - :wandb:runs[0][config][a]: 2
  - :wandb:runs[0][config][b]: testing
  - :wandb:runs[0][exitcode]: 0