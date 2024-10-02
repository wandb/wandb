from transformers import pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    qa_pipeline = pipeline(
        "question-answering", model="distilbert-base-cased-distilled-squad"
    )
    result = qa_pipeline(
        context=[
            "What is the capital of France?",
            "Who is the founder of Hugging Face?",
        ],
        question=[
            "The capital of France is Paris.",
            "Hugging Face was founded by Clément Delangue and Julien Chaumond.",
        ],
        top_k=2,
    )
    print(result)


if __name__ == "__main__":
    main()
