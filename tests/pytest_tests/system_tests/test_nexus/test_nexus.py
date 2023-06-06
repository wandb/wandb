def test_wandb_init(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init()
        run.log({"nexus": 1337})
        history = relay.context.get_run_history(run.id)
        assert history[0]["nexus"] == 1337
        run.finish()
