import openai

from wandb.integration.openai import autolog

autolog(project="openai_logging")


def main():
    request_kwargs = dict(
        engine="ada",
        prompt="This is a test prompt",
        max_tokens=5,
        temperature=0.9,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )

    response = openai.Completion.create(**request_kwargs)


if __name__ == "__main__":
    main()
