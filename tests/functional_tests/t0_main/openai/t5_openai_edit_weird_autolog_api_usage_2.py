import openai
import wandb
from wandb.integration.openai import autolog


def main():
    # emulate the situation where there is a run already created by the user
    run = wandb.init(project="skunkworks")  # noqa: F841

    assert autolog._run is None
    assert autolog._AutologOpenAI__run_created_by_autolog is False

    autolog.enable(init={"project": "marmotworks"})

    assert autolog._run is not None
    assert autolog._AutologOpenAI__run_created_by_autolog is False
    assert wandb.run.settings.project == "skunkworks"

    autolog.enable(init={"project": "groundsquirrelworks"})

    assert autolog._run is not None
    assert autolog._AutologOpenAI__run_created_by_autolog is False
    assert wandb.run.settings.project == "skunkworks"

    request_kwargs = dict(
        model="text-davinci-edit-001",
        input="To bee or not to bee?",
        instruction="Fix the spelling mistakes.",
    )

    _ = openai.Edit.create(**request_kwargs)

    autolog.disable()
    assert autolog._run is None
    assert autolog._AutologOpenAI__run_created_by_autolog is False
    assert wandb.run is not None


if __name__ == "__main__":
    main()
