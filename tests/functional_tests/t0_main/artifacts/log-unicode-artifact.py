import wandb


def main():
    with wandb.init() as run:
        artifact = wandb.Artifact("my_artifact", type="unicode_artifact")
        with artifact.new_file("euler.txt", mode="w", encoding="utf-8") as f:
            f.write("e^(iπ)+1=0")

        run.log_artifact(artifact)


if __name__ == "__main__":
    main()
