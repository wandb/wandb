import datetime


def simple_fake_test(handler):
    from langchain.chains import LLMChain
    from langchain.llms.fake import FakeListLLM
    from langchain.prompts import PromptTemplate

    llm = FakeListLLM(responses=[f"Fake response: {i}" for i in range(100)])

    prompt = PromptTemplate(
        input_variables=["product"],
        template="What is a good name for a company that makes {product}?",
    )

    chain = LLMChain(llm=llm, prompt=prompt, callbacks=[handler])

    for i in range(10):
        chain(f"q: {i} - {datetime.datetime.now().timestamp()}")


def main():
    from wandb.integration.langchain import WandbTracer

    handler = WandbTracer()
    simple_fake_test(handler)
    handler.finish()


main()
