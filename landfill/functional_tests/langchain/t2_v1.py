from langchain.agents import AgentType, initialize_agent, load_tools
from langchain.llms import OpenAI

# Agent run with tracing. Ensure that OPENAI_API_KEY is set appropriately to run this example.


def check_agent(handler):
    llm = OpenAI(temperature=0)
    tools = load_tools(["llm-math"], llm=llm)

    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
    )

    agent.run("What is 2 raised to .123243 power?", callbacks=[handler])


def main():
    from wandb.integration.langchain import WandbTracer

    handler = WandbTracer()
    check_agent(handler)
    handler.finish()


main()
