import os

from openai import OpenAI
from wandb.integration.openai.fine_tuning import WandbLogger


def main():
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    # Not sending the data for finetuning, instead using a complete fine-tune job
    # to check if all the functionalities of `WandbLogger` are working.
    WandbLogger.sync(
        fine_tune_job_id="ftjob-H3DHssnC1C82qfc3ePQWeP3V", openai_client=client
    )


if __name__ == "__main__":
    main()
