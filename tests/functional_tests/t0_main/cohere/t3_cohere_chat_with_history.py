import cohere
from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    co = cohere.Client()

    _ = co.chat(
        query="Give me your favorite Math Rock song!",
        model="command-light",
        chat_history=[
            {"user_name": "User", "text": "Hey! How are you doing today?"},
            {"user_name": "Bot", "text": "I am doing great! How can I help you?"},
        ],
        return_prompt=True,
        return_preamble=True,
        return_chatlog=True,
    )

    _ = co.chat(
        query="Give me your favorite Math Rock song!",
        model="command-light",
        chat_history=[
            {"user_name": "User", "text": "What is your favorite Genre?"},
            {"user_name": "Bot", "text": "Have you listened to Math Rock?"},
        ],
    )


if __name__ == "__main__":
    main()
