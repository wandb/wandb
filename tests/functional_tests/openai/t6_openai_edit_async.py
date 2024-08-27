import asyncio

import openai
from wandb.integration.openai import autolog as openai_autolog

openai_autolog(init=dict(project="openai_logging"))


def main():
    request_kwargs = dict(
        model="text-davinci-edit-001",
        input="To bee or not to bee?",
        instruction="Fix the spelling mistakes.",
    )

    _ = asyncio.run(openai.Edit.acreate(**request_kwargs))


if __name__ == "__main__":
    main()
