from wandb.apis import internal


def test_get_run_state(test_settings):
    _api = internal.Api()
    res = _api.get_run_state("test", "test", "test")
    assert res == "running", "Test run must have state running"
