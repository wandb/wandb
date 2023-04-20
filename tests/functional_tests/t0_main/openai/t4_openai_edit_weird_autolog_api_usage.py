import openai
import wandb
from wandb.integration.openai import autolog


def main():
    # emulate the situation where there is no run created by the user

    assert autolog._run is None
    assert autolog._AutologOpenAI__run_created_by_autolog is False

    autolog.enable(init={"project": "skunkworks"})

    assert autolog._run is not None
    assert autolog._AutologOpenAI__run_created_by_autolog
    assert wandb.run.settings.project == "skunkworks"

    autolog.enable(init={"project": "groundsquirrelworks"})

    assert autolog._run is not None
    assert autolog._AutologOpenAI__run_created_by_autolog
    assert wandb.run.settings.project == "groundsquirrelworks"

    request_kwargs = dict(
        model="text-davinci-edit-001",
        input="To bee or not to bee?",
        instruction="Fix the spelling mistakes.",
    )

    _ = openai.Edit.create(**request_kwargs)

    autolog.disable()
    assert autolog._run is None
    assert autolog._AutologOpenAI__run_created_by_autolog is False
    assert wandb.run is None


if __name__ == "__main__":
    main()
