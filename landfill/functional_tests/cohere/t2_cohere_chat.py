import cohere

from wandb.integration.cohere import autolog as cohere_autolog

cohere_autolog()


def main():
    co = cohere.Client()

    response = co.chat(
        message="Hey! How are you doing today?",
        model="command-light",
        return_prompt=True,
        return_preamble=True,
    )
    conv_session_id = response.conversation_id
    _ = co.chat(
        message="What's your plan for the day?",
        conversation_id=conv_session_id,
        model="command-light",
    )


if __name__ == "__main__":
    main()
