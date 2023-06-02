import openai
from wandb.integration.openai import autolog as openai_autolog


def main():
    openai_autolog(init=dict(project="openai_logging"))
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
    openai_autolog.disable()


if __name__ == "__main__":
    main()
