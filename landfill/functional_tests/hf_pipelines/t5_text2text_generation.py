from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    text2text_generation_pipeline = pipeline("text2text-generation")
    result = text2text_generation_pipeline(
        ["I love playing football.", "I study machine learning."]
    )
    print(result)  # Will vary each time, e.g.:


if __name__ == "__main__":
    main()
