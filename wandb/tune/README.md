# wandb ray/tune local sweep controller


Search algorithms:

 | Name                                                                                                                 | Supported | Example                              |
 | -------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------------------ |
 | [hyperopt](https://github.com/hyperopt/hyperopt)                                                                     | Yes       | [Yes](examples/hyperopt_example.py)  |
 | [nevergrad](https://github.com/facebookresearch/nevergrad)                                                           | Yes       | [Yes](examples/nevergrad_example.py) |
 | [grid/random](https://ray.readthedocs.io/en/latest/tune-searchalg.html#variant-generation-grid-search-random-search) | No        |
 | [bayes](https://ray.readthedocs.io/en/latest/tune-searchalg.html#bayesopt-search)                                    | No        |
 | [sigopt](https://ray.readthedocs.io/en/latest/tune-searchalg.html#sigopt-search)                                     | No        |
 | [scikit-optimize](https://ray.readthedocs.io/en/latest/tune-searchalg.html#scikit-optimize-search)                   | No        |
 | [Ax](https://ax.dev/)                                                                                                | No        |

Schedling Algorithms:

  | Name                                                                                                                       | Supported | Example                             |
  | -------------------------------------------------------------------------------------------------------------------------- | --------- | ----------------------------------- |
  | [Hyperband (async)](https://ray.readthedocs.io/en/latest/tune-schedulers.html#asynchronous-hyperband)                      | Yes       | [Yes](examples/hyperopt_example.py) |
  | [Hyperband](https://ray.readthedocs.io/en/latest/tune-schedulers.html#hyperband)                                           | No        |
  | [Median Stopping](https://ray.readthedocs.io/en/latest/tune-schedulers.html#median-stopping-rule)                          | No        |
  | [Population Based Training (PBT)](https://ray.readthedocs.io/en/latest/tune-schedulers.html#population-based-training-pbt) | No        |

