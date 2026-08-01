import sys

import wandb

# For use with test_pyagent.py::test_agent_subprocess_with_import_readline


def main() -> None:
    with wandb.init() as run:
        print("Importing readline...")
        # `import readline` causes deadlock if parent launches subprocess using
        # progress_group=0 without a pty
        import readline  # noqa: F401

        print("Imported readline.")

        got_eof = False
        try:
            user_input = input("Enter something: ")
            print(f"Got unexpected input (expected EOFError): {user_input}")
        except EOFError:
            print("Got EOFError as expected (parent stdin closed)")
            got_eof = True
        except Exception as e:
            print(f"Unexpected error: {e}")

        run.log(
            {
                "test_param": run.config.test_param,
                "got_eof": got_eof,
            }
        )

    if not got_eof:
        sys.exit(1)


if __name__ == "__main__":
    main()
