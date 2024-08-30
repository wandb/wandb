import cohere

from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    co = cohere.Client()

    docs = [
        "Carson City is the capital city of the American state of Nevada.",
        "The Commonwealth of the Northern Mariana Islands is a group of islands in the Pacific Ocean. Its capital is Saipan.",
        "Washington, D.C. (also known as simply Washington or D.C., and officially as the District of Columbia) is the capital of the United States. It is a federal district.",
        "Capital punishment (the death penalty) has existed in the United States since beforethe United States was a country. As of 2017, capital punishment is legal in 30 of the 50 states.",
    ]
    _ = co.rerank(
        model="rerank-english-v2.0",
        query="What is the capital of the United States?",
        documents=docs,
        top_n=3,
    )
    _ = co.rerank(
        model="rerank-english-v2.0",
        query="What is the capital of the United States?",
        documents=docs,
    )


if __name__ == "__main__":
    main()
