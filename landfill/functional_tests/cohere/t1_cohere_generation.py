import cohere

from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    co = cohere.Client()

    _ = co.generate(
        prompt="This Math Rock song is called",
    )

    _ = co.generate(
        model="command-light",
        prompt="Once upon a time in a magical land called",
        return_likelihoods="ALL",
        num_generations=2,
        temperature=1,
    )


if __name__ == "__main__":
    main()
