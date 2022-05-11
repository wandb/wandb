import wandb


def main():
    with wandb.init() as run:
        artifact = wandb.Artifact("my_artifact", type="unicode_artifact")
        with artifact.new_file("hello.txt", mode="w") as f:
            f.write("Привет, друзья")

        run.log_artifact(artifact)


if __name__ == "__main__":
    main()
