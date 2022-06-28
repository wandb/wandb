import wandb


def main():
    run = wandb.init(name=__file__)
    run.log({"boom": 1})
    run.finish()


if __name__ == "__main__":
    main()
