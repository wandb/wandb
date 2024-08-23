# Functional Tests

## Example

Select the `xgboost` shard from the functional tests in `tests/functional_tests`,
and execute in a python 3.12 environment against a wandb server running at `http://localhost:8080`:

```shell
YEA_SHARD=xgboost \
WANDB_BASE_URL=http://localhost:8080 \ 
WANDB_API_KEY=myapikey \ 
nox -s "functional_tests-3.12(wandb_core)" -- tests/functional_tests
```
