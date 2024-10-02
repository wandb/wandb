from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    summarization_pipeline = pipeline("summarization")
    result = summarization_pipeline(
        [
            "Here is a long news article to summarize:...",
            "Here is another long news article to summarize:...",  # Truncated for clarity
        ],
        return_text=True,
    )
    print(result)


if __name__ == "__main__":
    main()
