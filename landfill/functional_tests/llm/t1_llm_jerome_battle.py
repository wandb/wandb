import cohere
import openai

from wandb.integration.cohere import autolog as cohere_autolog
from wandb.integration.openai import autolog as openai_autolog

cohere_autolog()
openai_autolog()


def main():
    # The API Key is stored in the environment variable CO_API_KEY
    co = cohere.Client()

    prompt = "There were four of us. George, and William Samuel Harris, and myself, and Montmorency."
    print("Prompt: ", prompt)

    prediction = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        max_tokens=25,
        temperature=0.1,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )
    response = prediction.choices[0].text
    print("OpenAI: ", response)

    # generate a prediction for a prompt
    prediction = co.generate(
        prompt=response,
        max_tokens=50,
    )

    response = prediction[0].text

    print("Cohere: ", response)


if __name__ == "__main__":
    main()
