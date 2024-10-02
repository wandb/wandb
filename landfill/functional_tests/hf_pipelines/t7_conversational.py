from transformers import Conversation, pipeline

from wandb.integration.huggingface import autolog as hf_autolog

hf_autolog()


def main():
    chatbot = pipeline("conversational", model="microsoft/DialoGPT-small")
    conversation1 = Conversation("Going to the movies tonight - any suggestions?")
    conversation2 = Conversation("What is the best anime in your opinion and why?")
    conversations = chatbot([conversation1, conversation2])
    print(conversations)

    conversation1 = conversations[0]

    conversation1.add_user_input("Is it an action movie?")
    conversation1 = chatbot(conversation1)
    print(conversation1)


if __name__ == "__main__":
    main()
