import cohere
from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    # initialize the Cohere Client with an API Key
    co = cohere.Client()

    # generate a prediction for a prompt
    prediction = co.generate(
        prompt=(
            "There were four of us. George, and William Samuel Harris, and myself, and Montmorency."
        ),
        max_tokens=30,
    )

    print(prediction)
    # breakpoint()

    # print the predicted text
    print(f"prediction: {prediction.generations[0].text}")

    # res = co.chat(query="Hey! How are you doing today?")
    # print(res)


if __name__ == "__main__":
    main()
