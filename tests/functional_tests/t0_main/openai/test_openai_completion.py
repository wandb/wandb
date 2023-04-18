import os

import openai

from wandb.integration.openai import autolog

openai.api_key = os.environ.get("OPENAI_API_KEY")
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

    _ = openai.Completion.create(**request_kwargs)


if __name__ == "__main__":
    main()
