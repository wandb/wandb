import os

from openai import OpenAI
from wandb.integration.openai.fine_tuning import WandbLogger


def main():
    client = OpenAI(
        base_url="https://api.endpoints.anyscale.com/v1",
        api_key=os.environ["ANYSCALE_ENDPOINT_TOKEN"]
    )
    # Not sending the data for finetuning, instead using a complete fine-tune job
    # to check if all the functionalities of `WandbLogger` are working.
    WandbLogger.sync(
        fine_tune_job_id="eftjob_h9imeeee8z2rkqml6ljy7w81we", openai_client=client
    )


if __name__ == "__main__":
    main()