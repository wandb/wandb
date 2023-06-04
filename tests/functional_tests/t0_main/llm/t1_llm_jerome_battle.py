import cohere
import openai
from wandb.integration.cohere import autolog as cohere_autolog
from wandb.integration.openai import autolog as openai_autolog

cohere_autolog()
openai_autolog()


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

    request_kwargs = dict(
        engine="text-davinci-003",
        prompt=prediction[0].text,
        max_tokens=25,
        temperature=0.1,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )

    prediction = openai.Completion.create(**request_kwargs)
    print(prediction.choices[0].text)


if __name__ == "__main__":
    main()
