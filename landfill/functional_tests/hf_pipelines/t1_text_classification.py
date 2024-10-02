from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    text_classification_pipeline = pipeline(
        "text-classification"
    )  # or sentiment-analysis
    result = text_classification_pipeline(
        [
            "This movie was awesome!",  # Positive
            "This movie was ok.",  # Neutral
            "This movie was terrible!",  # Negative
        ],
        top_k=2,
        function_to_apply="none",
    )
    print(result)


if __name__ == "__main__":
    main()
