import datetime
import sys

import wandb
from wandb.integration.langchain import WandbTracer
from wandb.sdk.data_types import trace_tree


def simple_fake_test():
    from langchain.chains import LLMChain
    from langchain.llms.fake import FakeListLLM
    from langchain.prompts import PromptTemplate

    llm = FakeListLLM(responses=[f"Fake response: {i}" for i in range(100)])

    prompt = PromptTemplate(
        input_variables=["product"],
        template="What is a good name for a company that makes {product}?",
    )

    chain = LLMChain(llm=llm, prompt=prompt)

    for i in range(10):
        chain(f"q: {i} - {datetime.datetime.now().timestamp()}")


def main():
    if sys.version_info <= (3, 8):
        # Special case to avoid langchain not supporting python 3.7
        run = wandb.init()
        run.log(
            {
                "langchain_traces": trace_tree.WBTraceTree(
                    root_span=trace_tree.Span(),
                    model_dict='{"model_name": "text-ada-001", "temperature": 0.7, "max_tokens": 256, "top_p": 1, "frequency_penalty": 0, "presence_penalty": 0, "n": 2, "best_of": 2, "request_timeout": null, "logit_bias": {}, "_kind": "openai"}',
                )
            }
        )
        run.finish()
        return

    WandbTracer.init()
    simple_fake_test()
    WandbTracer.finish()
