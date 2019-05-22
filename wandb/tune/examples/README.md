# wandb ray/tune examples

#### Examples:

- [hyperopt_example](hyperopt_example.py)

    Demonstrates:
    - AsyncHyperBandScheduler
    - HyperOptSearch

    ```
    terminal1> python hyperopt_example.py
    ```
    <details><summary>Output</summary>

    ```
    Sweep: zlm589un (unknown) | Runs: 0
    == Status ==
    Using AsyncHyperBand: num_stopped=0
    Bracket: Iter 90.000: None | Iter 30.000: None | Iter 10.000: None
    Bracket: Iter 90.000: None | Iter 30.000: None
    Bracket: Iter 90.000: None


    Start trial easy_objective_1_activation=tanh,height=2.0,iterations=100,width=4.0
    == Status ==
    Using AsyncHyperBand: num_stopped=0
    Bracket: Iter 90.000: None | Iter 30.000: None | Iter 10.000: None
    Bracket: Iter 90.000: None | Iter 30.000: None
    Bracket: Iter 90.000: None

    Number of trials: 4 ({'RUNNING': 1, 'PENDING': 3})
    PENDING trials:
     - easy_objective_2_activation=relu,height=2.0,iterations=100,width=1.0:	PENDING
     - easy_objective_3_activation=relu,height=68.891,iterations=100,width=11.822:	PENDING
     - easy_objective_4_activation=tanh,height=-5.1488,iterations=100,width=17.839:	PENDING
    RUNNING trials:
     - easy_objective_1_activation=tanh,height=2.0,iterations=100,width=4.0:	RUNNING
     ```
     </details>

    ```
    terminal2> wandb agent SWEEPID
    ```

    <details><summary>Output</summary>

    ```
    Starting wandb agent 🕵️
    2019-05-22 10:19:45,381 - wandb.agent - INFO - Running runs: []
    2019-05-22 10:19:45,498 - wandb.agent - INFO - Agent received command: run
    2019-05-22 10:19:45,498 - wandb.agent - INFO - Agent starting run with config:
	    _wandb_tune_run: True
	    activation: tanh
	    height: 2
	    iterations: 100
	    width: 4
    wandb: Started W&B process version 0.7.3.dev1 with PID 7555
    wandb: Local directory: wandb/run-20190522_171945-1wjsb69c
    wandb: Syncing to https://app.wandb.ai/jeffr/try-tune/runs/1wjsb69c
    wandb: Run `wandb off` to turn off syncing.
    wandb: Waiting for W&B process to finish, PID 7555
    wandb: Program ended successfully.
    2019-05-22 10:19:50,509 - wandb.agent - INFO - Running runs: ['1wjsb69c']
    wandb: Run summary:
    wandb:          _runtime 4.3772032260894775
    wandb:        _timestamp 1558545589.967666
    wandb:             _step 99
    wandb:   timesteps_total 99
    wandb:     neg_mean_loss -143
    wandb: Syncing files in wandb/run-20190522_171945-1wjsb69c:
    wandb:   diff.patch
    wandb: plus 6 W&B file(s) and 0 media file(s)
    wandb:                                                                                
    wandb: Synced https://app.wandb.ai/jeffr/try-tune/runs/1wjsb69c
    2019-05-22 10:19:55,625 - wandb.agent - INFO - Running runs: ['1wjsb69c']
    2019-05-22 10:19:55,626 - wandb.agent - INFO - Cleaning up dead run: 1wjsb69c
     ```
     </details>

- [nevergrad_example.py](nevergrad_example.py)

    Demonstrates:
    - AsyncHyperBandScheduler
    - NevergradSearch

    ```
    terminal1> python nevergrad_example.py 
    ```

    <details><summary>Output</summary>

    ```
    Create sweep with ID: an244yf2
    Sweep: an244yf2 (unknown) | Runs: 0
    == Status ==
    Using AsyncHyperBand: num_stopped=0
    Bracket: Iter 90.000: None | Iter 30.000: None | Iter 10.000: None
    Bracket: Iter 90.000: None | Iter 30.000: None
    Bracket: Iter 90.000: None


    Start trial easy_objective_1_height=0.0,iterations=100,width=0.0
    The `start_trial` operation took 0.8706541061401367 seconds to complete, which may be a performance bottleneck.
    == Status ==
    Using AsyncHyperBand: num_stopped=0
    Bracket: Iter 90.000: None | Iter 30.000: None | Iter 10.000: None
    Bracket: Iter 90.000: None | Iter 30.000: None
    Bracket: Iter 90.000: None

    Number of trials: 4 ({'RUNNING': 1, 'PENDING': 3})
    PENDING trials:
    - easy_objective_2_height=-0.076052,iterations=100,width=-0.57269:	PENDING
    - easy_objective_3_height=-0.18387,iterations=100,width=0.59924:	PENDING
    - easy_objective_4_height=2.1905,iterations=100,width=-0.82004:	PENDING
    RUNNING trials:
    - easy_objective_1_height=0.0,iterations=100,width=0.0:	RUNNING

    Start trial easy_objective_2_height=-0.076052,iterations=100,width=-0.57269
    Start trial easy_objective_3_height=-0.18387,iterations=100,width=0.59924
    Start trial easy_objective_4_height=2.1905,iterations=100,width=-0.82004
     ```
     </details>

    ```
    terminal2> wandb agent SWEEPID
    ```

    <details><summary>Output</summary>

    ```
    Starting wandb agent 🕵️
    2019-05-22 10:29:56,476 - wandb.agent - INFO - Running runs: []
    2019-05-22 10:29:56,599 - wandb.agent - INFO - Agent received command: run
    2019-05-22 10:29:56,599 - wandb.agent - INFO - Agent starting run with config:
        _wandb_tune_run: True
        height: 0
        iterations: 100
        width: 0
    wandb: Started W&B process version 0.7.3.dev1 with PID 8991
    wandb: Local directory: wandb/run-20190522_172956-01v3cicv
    wandb: Syncing to https://app.wandb.ai/jeffr/try-tune/runs/01v3cicv
    wandb: Run `wandb off` to turn off syncing.
    wandb: Waiting for W&B process to finish, PID 8991
    wandb: Program ended successfully.
    2019-05-22 10:30:01,611 - wandb.agent - INFO - Running runs: ['01v3cicv']
    wandb: Run summary:
    wandb:   timesteps_total 99
    wandb:             _step 99
    wandb:        _timestamp 1558546200.940673
    wandb:     neg_mean_loss -193
    wandb:          _runtime 4.24917197227478
    wandb: Syncing files in wandb/run-20190522_172956-01v3cicv:
    wandb:   diff.patch
    wandb: plus 6 W&B file(s) and 0 media file(s)
    wandb:                                                                                
    wandb: Synced https://app.wandb.ai/jeffr/try-tune/runs/01v3cicv
    2019-05-22 10:30:06,729 - wandb.agent - INFO - Running runs: ['01v3cicv']
    2019-05-22 10:30:06,730 - wandb.agent - INFO - Cleaning up dead run: 01v3cicv
    ```

#### Dependancies

The following are the packages (and commit hashes) which are dependancies for the wandb ray/tune local controller.

- ray/tune

  http://github.com/ray-project/ray @5693cd13442f3f17be690446d39c107ff759d10e

- nevergrad

  nevergrad                0.1.6 

- hyperopt

  hyperopt                 0.1.2 