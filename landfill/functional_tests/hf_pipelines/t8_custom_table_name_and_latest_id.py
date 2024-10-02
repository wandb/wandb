import os

from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    os.environ["WANDB_AUTOLOG_TABLE_NAME"] = "custom_table"
    text_classification_pipeline = pipeline("text-classification")
    result = text_classification_pipeline(
        [
            "Bocchi the Rock is amazing!",
        ]
    )
    print(result)
    print(hf_autolog.get_latest_id())


if __name__ == "__main__":
    main()
