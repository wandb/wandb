# import wandb

my_var = globals().get("my_var", "lol")


def main():
    print(my_var)


if __name__ == "__main__":
    main()
