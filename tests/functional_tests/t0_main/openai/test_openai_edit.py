import os

import openai

from wandb.integration.openai import autolog

openai.api_key = os.environ.get("OPENAI_API_KEY")
autolog(project="openai_logging")


def main():
    request_kwargs = dict(
        model="text-davinci-edit-001",
        input="What day of the wek is it?",
        instruction="Fix the spelling mistakes.",
    )

    _ = openai.Edit.create(**request_kwargs)


if __name__ == "__main__":
    main()
