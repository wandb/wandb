import os
import time

import wandb


def main():
    # Remove ~/.netrc so there is no key in it
    netrc_path = os.path.expanduser("~/.netrc")
    if os.path.exists(netrc_path):
        print(f"Removing {netrc_path}")
        os.remove(netrc_path)
    else:
        print(f"{netrc_path} does not exist")

    with open("key.txt", "r") as f:
        api_key = f.read().strip()

    # FIXME: endup seeing the login screen instead of the key from wandb.init
    with wandb.init(
        project="log-artifact-api-key",
        entity="reg-team-2",
        settings=wandb.Settings(api_key=api_key),
    ) as run:
        artifact = wandb.Artifact("my-artifact", type="dataset")
        # Create a new file every time
        with open("time.md", "w") as f:
            f.write(
                "This is a test artifact created at "
                + time.strftime("%Y-%m-%d %H:%M:%S")
            )
        artifact.add_file("time.md")
        run.log_artifact(artifact)

    # Check if .netrc exists
    if os.path.exists(netrc_path):
        print(f"{netrc_path} exists")
    else:
        print(f"{netrc_path} does not exist")


if __name__ == "__main__":
    main()
