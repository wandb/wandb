import cohere

from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    co = cohere.Client()

    _ = co.chat(
        message="What is the weather like today?",
        model="command-light",
        chat_history=[
            {"user_name": "User", "message": "Hey! How are you doing today?"},
            {"user_name": "Bot", "message": "I am doing great! How can I help you?"},
        ],
        return_prompt=True,
        return_preamble=True,
    )

    _ = co.chat(
        message="How many people live in New York City?",
        model="command-light",
        chat_history=[
            {"user_name": "User", "message": "Hi! How are you doing today?"},
            {"user_name": "Bot", "message": "I am doing great! How can I help you?"},
        ],
    )


if __name__ == "__main__":
    main()
