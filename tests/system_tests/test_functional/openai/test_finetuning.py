from __future__ import annotations

import os

import pytest
from openai import OpenAI
from wandb.integration.openai.fine_tuning import WandbLogger


@pytest.mark.skip(reason="flaky")
def test_finetuning(wandb_backend_spy):
    # TODO: this does not test much, it should be improved
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Not sending the data for finetuning, instead using a complete fine-tune job
    # to check if all the functionalities of `WandbLogger` are working.
    WandbLogger.sync(
        fine_tune_job_id="ftjob-H3DHssnC1C82qfc3ePQWeP3V", openai_client=client
    )

    WandbLogger._run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1

        run_id = run_ids.pop()

        config = snapshot.config(run_id=run_id)
        assert config["training_file"]["value"] == "file-r3A6hLffY2cEXBUPoEfJSPkC"
        assert config["validation_file"]["value"] == "file-z2xYlp21ljsfc7mXBcX1Jimg"

        summary = snapshot.summary(run_id=run_id)
        assert (
            summary["fine_tuned_model"]
            == "ft:gpt-3.5-turbo-0613:weights-biases::8KWIS3Yj"
        )
        assert summary["status"] == "succeeded"
        assert summary["train_accuracy"] == 1.0
        assert summary["valid_mean_token_accuracy"] == 0.33333
