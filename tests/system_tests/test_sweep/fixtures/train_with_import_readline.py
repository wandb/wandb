# import readline to trigger setpgid concurrency issue
import wandb

# For use with system_tests/test_sweep/test_wandb_agent_full.py

def main(
    project: str = "train-with-import-readline",
):
    print("Train with import readline")
    run = wandb.init(
        project=project,
    )
    test_param = wandb.config.test_param
    print("run_id:", run.id)

    print("Importing readline...")
    import readline  # noqa: F401
    print("Imported readline.")

    run.log(
          {
            "test_param": test_param,
          })

    run.finish()


if __name__ == "__main__":
    main()
