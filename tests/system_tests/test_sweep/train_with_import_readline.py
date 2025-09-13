import wandb

# For use with ../test_wandb_agent_full.py::test_agent_subprocess_with_import_readline


def main() -> None:
    with wandb.init() as run:
        print("Importing readline...")
        # `import readline` causes deadlock if parent launches subprocess using progress_group=0
        import readline  # noqa: F401

        print("Imported readline.")

        run.log({"test_param": run.config.test_param})


if __name__ == "__main__":
    main()
