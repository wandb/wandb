# Log artifact using API key

## public_api in run

Inside `__public_api` method, it creates a new `public.Api` without using settings from the run.

```text
wandb: Syncing run trembling-mist-3
wandb: ⭐️ View project at https://wandb.ai/reg-team-2/log-artifact-api-key
wandb: 🚀 View run at https://wandb.ai/reg-team-2/log-artifact-api-key/runs/sbfb46ay
Traceback (most recent call last):
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/hack/log_api.py", line 33, in main
    run.log_artifact(artifact)
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 397, in wrapper
    return func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 455, in wrapper_fn
    return func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 442, in wrapper
    return func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 3138, in log_artifact
    return self._log_artifact(
           ^^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 3289, in _log_artifact
    self._assert_can_log_artifact(artifact)
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 3337, in _assert_can_log_artifact
    public_api = self._public_api()
                 ^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_run.py", line 3330, in _public_api
    return public.Api(overrides)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/apis/public/api.py", line 323, in __init__
    wandb_login._verify_login(
  File "/Users/pinglei.guo/go/src/github.com/wandb/wandb/wandb/sdk/wandb_login.py", line 367, in _verify_login
    raise AuthenticationError(
wandb.errors.errors.AuthenticationError: API key verification failed for host https://api.wandb.ai. Make sure your API key is valid.
wandb: 🚀 View run trembling-mist-3 at: https://wandb.ai/reg-team-2/log-artifact-api-key/runs/sbfb46ay
wandb: ⭐️ View project at: https://wandb.ai/reg-team-2/log-artifact-api-key
```
