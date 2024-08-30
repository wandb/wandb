from transformers import pipeline
from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    text_generation_pipeline = pipeline("text-generation")
    results = text_generation_pipeline(["Once upon a time,", "In the year 2525,"])
    print(results)  # Will vary each time, e.g.:


if __name__ == "__main__":
    main()
