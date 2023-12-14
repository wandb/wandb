def test_wandb_init(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log({"core": 1337})
        run.finish()
    history = relay.context.get_run_history(run.id)
    assert history["core"][0] == 1337


# TODO: this is just a smoke test to make sure we don't break offline mode
# remove it when we enable all the tests for core
def test_wandb_init_offline(relay_server, wandb_init):
    with relay_server():
        run = wandb_init(settings={"mode": "offline"})
        run.log({"core": 1337})
        run.finish()
