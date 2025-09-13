import wandb

# For use with ../test_wandb_agent_full.py::test_agent_subprocess_with_pty_error

def main(r) -> None:
    with wandb.init() as run:
        run.log({"test_param": run.config.test_param})

if __name__ == "__main__":
    main()
