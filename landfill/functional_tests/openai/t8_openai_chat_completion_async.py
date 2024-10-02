import asyncio

import openai

from wandb.integration.openai import autolog as openai_autolog


def main():
    openai_autolog(init=dict(project="openai_logging"))
    request_kwargs = dict(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Who won the world series in 2020?"},
            {
                "role": "assistant",
                "content": "The Los Angeles Dodgers won the World Series in 2020.",
            },
            {"role": "user", "content": "Where was it played?"},
        ],
    )

    _ = asyncio.run(openai.ChatCompletion.acreate(**request_kwargs))


if __name__ == "__main__":
    main()
