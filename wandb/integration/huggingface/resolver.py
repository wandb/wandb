import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pytz

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from wandb.sdk.lib.runid import generate_id

logger = logging.getLogger(__name__)

SUPPORTED_PIPELINE_TASKS = [
    "text-classification",
    "sentiment-analysis",
    "question-answering",
    "summarization",
    "translation",
    "text2text-generation",
    "text-generation",
    # "conversational",
]

PIPELINES_WITH_TOP_K = [
    "text-classification",
    "sentiment-analysis",
    "question-answering",
]


class HuggingFacePipelineRequestResponseResolver:
    """Resolver for HuggingFace's pipeline request and responses, providing necessary data transformations and formatting.

    This is based off (from wandb.sdk.integration_utils.auto_logging import RequestResponseResolver)
    """

    autolog_id = None

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Optional[Dict[str, Any]]:
        """Main call method for this class.

        :param args: list of arguments
        :param kwargs: dictionary of keyword arguments
        :param response: the response from the request
        :param start_time: time when request started
        :param time_elapsed: time elapsed for the request
        :returns: packed data as a dictionary for logging to wandb, None if an exception occurred
        """
        try:
            pipe, input_data = args[:2]
            task = pipe.task

            # Translation tasks are in the form of `translation_x_to_y`
            if task in SUPPORTED_PIPELINE_TASKS or task.startswith("translation"):
                model = self._get_model(pipe)
                if model is None:
                    return None
                model_alias = model.name_or_path
                timestamp = datetime.now(pytz.utc)

                input_data, response = self._transform_task_specific_data(
                    task, input_data, response
                )
                formatted_data = self._format_data(task, input_data, response, kwargs)
                packed_data = self._create_table(
                    formatted_data, model_alias, timestamp, time_elapsed
                )
                table_name = os.environ.get("WANDB_AUTOLOG_TABLE_NAME", f"{task}")
                # TODO: Let users decide the name in a way that does not use an environment variable

                return {
                    table_name: wandb.Table(
                        columns=packed_data[0], data=packed_data[1:]
                    )
                }

            logger.warning(
                f"The task: `{task}` is not yet supported.\nPlease contact `wandb` to notify us if you would like support for this task"
            )
        except Exception as e:
            logger.warning(e)
        return None

    # TODO: This should have a dependency on PreTrainedModel. i.e. isinstance(PreTrainedModel)
    # from transformers.modeling_utils import PreTrainedModel
    # We do not want this dependency explicitly in our codebase so we make a very general
    # assumption about the structure of the pipeline which may have unintended consequences
    def _get_model(self, pipe) -> Optional[Any]:
        """Extracts model from the pipeline.

        :param pipe: the HuggingFace pipeline
        :returns: Model if available, None otherwise
        """
        model = pipe.model
        try:
            return model.model
        except AttributeError:
            logger.info(
                "Model does not have a `.model` attribute. Assuming `pipe.model` is the correct model."
            )
            return model

    @staticmethod
    def _transform_task_specific_data(
        task: str, input_data: Union[List[Any], Any], response: Union[List[Any], Any]
    ) -> Tuple[Union[List[Any], Any], Union[List[Any], Any]]:
        """Transform input and response data based on specific tasks.

        :param task: the task name
        :param input_data: the input data
        :param response: the response data
        :returns: tuple of transformed input_data and response
        """
        if task == "question-answering":
            input_data = input_data if isinstance(input_data, list) else [input_data]
            input_data = [data.__dict__ for data in input_data]
        elif task == "conversational":
            # We only grab the latest input/output pair from the conversation
            # Logging the whole conversation renders strangely.
            input_data = input_data if isinstance(input_data, list) else [input_data]
            input_data = [data.__dict__["past_user_inputs"][-1] for data in input_data]

            response = response if isinstance(response, list) else [response]
            response = [data.__dict__["generated_responses"][-1] for data in response]
        return input_data, response

    def _format_data(
        self,
        task: str,
        input_data: Union[List[Any], Any],
        response: Union[List[Any], Any],
        kwargs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Formats input data, response, and kwargs into a list of dictionaries.

        :param task: the task name
        :param input_data: the input data
        :param response: the response data
        :param kwargs: dictionary of keyword arguments
        :returns: list of dictionaries containing formatted data
        """
        input_data = input_data if isinstance(input_data, list) else [input_data]
        response = response if isinstance(response, list) else [response]

        formatted_data = []
        for i_text, r_text in zip(input_data, response):
            # Unpack single element responses for better rendering in wandb UI when it is a task without top_k
            # top_k = 1 would unpack the response into a single element while top_k > 1 would be a list
            # this would cause the UI to not properly concatenate the tables of the same task by omitting the elements past the first
            if (
                (isinstance(r_text, list))
                and (len(r_text) == 1)
                and task not in PIPELINES_WITH_TOP_K
            ):
                r_text = r_text[0]
            formatted_data.append(
                {"input": i_text, "response": r_text, "kwargs": kwargs}
            )
        return formatted_data

    def _create_table(
        self,
        formatted_data: List[Dict[str, Any]],
        model_alias: str,
        timestamp: float,
        time_elapsed: float,
    ) -> List[List[Any]]:
        """Creates a table from formatted data, model alias, timestamp, and elapsed time.

        :param formatted_data: list of dictionaries containing formatted data
        :param model_alias: alias of the model
        :param timestamp: timestamp of the data
        :param time_elapsed: time elapsed from the beginning
        :returns: list of lists, representing a table of data. [0]th element = columns. [1]st element = data
        """
        header = [
            "ID",
            "Model Alias",
            "Timestamp",
            "Elapsed Time",
            "Input",
            "Response",
            "Kwargs",
        ]
        table = [header]
        autolog_id = generate_id(length=16)

        for data in formatted_data:
            row = [
                autolog_id,
                model_alias,
                timestamp,
                time_elapsed,
                data["input"],
                data["response"],
                data["kwargs"],
            ]
            table.append(row)

        self.autolog_id = autolog_id

        return table

    def get_latest_id(self):
        return self.autolog_id
