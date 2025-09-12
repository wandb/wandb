import wandb

# For use with ../test_wandb_agent_full.py::test_agent_subprocess_with_pty_error


def main(
    project: str = "train-basic",
):
    print("Train basic")
    run = wandb.init(
        project=project,
    )
    test_param = wandb.config.test_param
    print("run_id:", run.id)

    run.log({"test_param": test_param})
    run.finish()


if __name__ == "__main__":
    main()
