import os

from openai import OpenAI
from wandb.integration.openai.fine_tuning import WandbLogger


def test_finetuning(user, relay_server):
    # TODO: this does not test much, it should be improved
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    with relay_server() as relay:
        # Not sending the data for finetuning, instead using a complete fine-tune job
        # to check if all the functionalities of `WandbLogger` are working.
        WandbLogger.sync(
            fine_tune_job_id="ftjob-H3DHssnC1C82qfc3ePQWeP3V", openai_client=client
        )

        WandbLogger._run.finish()

    context = relay.context
    run_ids = context.get_run_ids()
    assert len(run_ids) == 1

    run_id = run_ids[0]

    config = context.get_run_config(run_id)
    assert config["training_file"]["value"] == "file-r3A6hLffY2cEXBUPoEfJSPkC"
    assert config["validation_file"]["value"] == "file-z2xYlp21ljsfc7mXBcX1Jimg"

    summary = context.get_run_summary(run_id)
    assert (
        summary["fine_tuned_model"] == "ft:gpt-3.5-turbo-0613:weights-biases::8KWIS3Yj"
    )
    assert summary["status"] == "succeeded"
    assert summary["train_accuracy"] == 1.0
    assert summary["valid_mean_token_accuracy"] == 0.33333
