import cohere
from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    # The API Key is stored in the environment variable CO_API_KEY
    co = cohere.Client()

    # generate a prediction for a prompt
    prediction = co.generate(
        prompt=(
            "There were four of us. George, and William Samuel Harris, and myself, and Montmorency."
        ),
        max_tokens=30,
    )

    print(prediction[0].text)


if __name__ == "__main__":
    main()
