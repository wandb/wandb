from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    translation_pipeline = pipeline("translation_en_to_fr")
    result = translation_pipeline(["Hello!", "How are you?"])
    print(result)


if __name__ == "__main__":
    main()
