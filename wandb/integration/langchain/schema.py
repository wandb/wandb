# Langchain defines tracer schema in `langchain/callbacks/tracers/schemas.py`
# As of this writing, we are on commit `https://github.com/hwchase17/langchain/commit/90d5328eda2bf5203a6311c1c15426b66039e5bc`.
# The schema used by LangChain is:
"""
class BaseRun(BaseModel):
    id: Optional[Union[int, str]] = None
    start_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    end_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    extra: Optional[Dict[str, Any]] = None
    execution_order: int
    serialized: Dict[str, Any]
    session_id: int
    error: Optional[str] = None

class LLMResult(BaseModel):
    generations: List[List[Generation]]
    llm_output: Optional[dict] = None


class LLMRun(BaseRun):
    prompts: List[str]
    response: Optional[LLMResult] = None


class ChainRun(BaseRun):
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    child_llm_runs: List[LLMRun] = Field(default_factory=list)
    child_chain_runs: List[ChainRun] = Field(default_factory=list)
    child_tool_runs: List[ToolRun] = Field(default_factory=list)
    child_runs: List[Union[LLMRun, ChainRun, ToolRun]] = Field(default_factory=list)


class ToolRun(BaseRun):
    tool_input: str
    output: Optional[str] = None
    action: str
    child_llm_runs: List[LLMRun] = Field(default_factory=list)
    child_chain_runs: List[ChainRun] = Field(default_factory=list)
    child_tool_runs: List[ToolRun] = Field(default_factory=list)
    child_runs: List[Union[LLMRun, ChainRun, ToolRun]] = Field(default_factory=list)
"""

# In this file, we define parallel schema so that we can rely on a constant
# schema in the UI. If LangChain changes their schema, then the integration
# layer (inside LangChain) can be trivially updated to convert the new schema to
# the old schema. Here, we are going to define a subset which is used in the UI.

import typing


class WBLCBaseRun(typing.TypedDict):
    id: typing.Optional[typing.Union[int, str]]
    start_time: int
    end_time: int
    # We are not including an extra field here because it is unbounded.
    # extra: typing.Any
    execution_order: int
    # We are not including a serialized field here because it is unbounded.
    # serialized: typing.Dict[str, str]
    session_id: int
    error: typing.Optional[str]
    # This is an additional field that is used for the human-readable name of the run type
    # In most cases this should be the name of the class (eg. OpenAi). It will be extracted
    # from the serialized field from the integration.
    run_type_name: str


class WBLCLLMResponse(typing.TypedDict):
    prompt: str
    generation: typing.Optional[str]


class WBLCLLMRun(WBLCBaseRun):
    # Here, we deviate from LangChain's schema. LangChain uses a schema where there prompts
    # are their own field, then they have a list of generations, which is a doubly-nested
    # list. In practice, this can be simplified to N list of generations, where each generation
    # is a single prompt and generation.
    prompt_responses: typing.List[WBLCLLMResponse]
    # prompts: List[str]
    # response: Optional[LLMResult] = None


class WBLCChainRun(WBLCBaseRun):
    inputs: typing.Dict[str, typing.Any]
    outputs: typing.Optional[typing.Dict[str, typing.Any]]
    # Again, we deviate from LangChain's schema. LangChain uses a schema where they have
    # each child run type in its own field AND a list of all child runs. In practice, this
    # is not as efficient as just having a list of all child runs.
    # child_llm_runs: typing.List[LLMRunTrace]
    # child_chain_runs: typing.List[ChainRunTrace]
    # child_tool_runs: typing.List[ToolRunTrace]
    child_runs: typing.List[typing.Union["WBLCLLMRun", "WBLCChainRun", "WBLCToolRun"]]


class WBLCToolRun(WBLCBaseRun):
    tool_input: str
    output: typing.Optional[str]
    action: str
    # Again, we deviate from LangChain's schema. LangChain uses a schema where they have
    # each child run type in its own field AND a list of all child runs. In practice, this
    # is not as efficient as just having a list of all child runs.
    # child_llm_runs: typing.List[LLMRunTrace]
    # child_chain_runs: typing.List[ChainRunTrace]
    # child_tool_runs: typing.List[ToolRunTrace]
    child_runs: typing.List[typing.Union["WBLCLLMRun", "WBLCChainRun", "WBLCToolRun"]]
