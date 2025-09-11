import wandb

# For use with ../test_wandb_agent_full.py::test_agent_subprocess_with_import_readline


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
    # `import readline` causes deadlock if parent launches subprocess using progress_group=0
    # without a pty
    import readline  # noqa: F401

    print("Imported readline.")

    try:
        user_input = input("Enter something: ")
        print(f"Got unexpected input (expected EOFError): {user_input}")
    except EOFError:
        print("Got EOFError as expected (parent stdin closed)")
    except Exception as e:
        print(f"Unexpected error: {e}")

    run.log({"test_param": test_param})
    run.finish()


if __name__ == "__main__":
    main()
