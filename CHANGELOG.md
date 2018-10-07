## 0.16.20 (October 5, 2018)

#### :bug: Bug Fix

- The first image when calling wandb.log was not being written, now it is
- `wandb.log` and `run.summary` now remove whitespace from keys

## 0.16.19 (October 5, 2018)

#### :bug: Bug Fix

- Vendored prompt_toolkit < 1.0.15 because the latest ipython is pinned > 2.0
- Lazy load wandb.h5 only if `summary` is accessed to improve Data API performance

#### :nail_care: Enhancement

- Jupyter
  - Deprecated `wandb.monitor` in favor of automatically starting system metrics after the first wandb.log call
  - Added new **%%wandb** jupyter magic method to display live results
  - Removed jupyter description iframe 
- The Data API now supports `per_page` and `order` options to the `api.runs` method
- Initial support for wandb.Table logging
- Initial support for matplotlib logging
