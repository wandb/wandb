import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from wandb.sdk.lib.runid import generate_id

logger = logging.getLogger(__name__)


def subset_dict(
    original_dict: Dict[str, Any], keys_subset: Sequence[str]
) -> Dict[str, Any]:
    """Create a subset of a dictionary using a subset of keys.

    :param original_dict: The original dictionary.
    :param keys_subset: The subset of keys to extract.
    :return: A dictionary containing only the specified keys.
    """
    return {key: original_dict[key] for key in keys_subset if key in original_dict}


def reorder_and_convert_dict_list_to_table(
    data: List[Dict[str, Any]], order: List[str]
) -> Tuple[List[str], List[List[Any]]]:
    """Convert a list of dictionaries to a pair of column names and corresponding values, with the option to order specific dictionaries.

    :param data: A list of dictionaries.
    :param order: A list of keys specifying the desired order for specific dictionaries. The remaining dictionaries will be ordered based on their original order.
    :return: A pair of column names and corresponding values.
    """
    final_columns = []
    keys_present = set()

    # First, add all ordered keys to the final columns
    for key in order:
        if key not in keys_present:
            final_columns.append(key)
            keys_present.add(key)

    # Then, add any keys present in the dictionaries but not in the order
    for d in data:
        for key in d:
            if key not in keys_present:
                final_columns.append(key)
                keys_present.add(key)

    # Then, construct the table of values
    values = []
    for d in data:
        row = []
        for key in final_columns:
            row.append(d.get(key, None))
        values.append(row)

    return final_columns, values


def flatten_dict(
    dictionary: Dict[str, Any], parent_key: str = "", sep: str = "-"
) -> Dict[str, Any]:
    """Flatten a nested dictionary, joining keys using a specified separator.

    :param dictionary: The dictionary to flatten.
    :param parent_key: The base key to prepend to each key.
    :param sep: The separator to use when joining keys.
    :return: A flattened dictionary.
    """
    flattened_dict = {}
    for key, value in dictionary.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            flattened_dict.update(flatten_dict(value, new_key, sep=sep))
        else:
            flattened_dict[new_key] = value
    return flattened_dict


def collect_common_keys(list_of_dicts: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Collect the common keys of a list of dictionaries. For each common key, put its values into a list in the order they appear in the original dictionaries.

    :param list_of_dicts: The list of dictionaries to inspect.
    :return: A dictionary with each common key and its corresponding list of values.
    """
    common_keys = set.intersection(*map(set, list_of_dicts))
    common_dict = {key: [] for key in common_keys}
    for d in list_of_dicts:
        for key in common_keys:
            common_dict[key].append(d[key])
    return common_dict


class CohereRequestResponseResolver:
    """Class to resolve the request/response from the Cohere API and convert it to a dictionary that can be logged."""

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Optional[Dict[str, Any]]:
        """Process the response from the Cohere API and convert it to a dictionary that can be logged.

        :param args: The arguments of the original function.
        :param kwargs: The keyword arguments of the original function.
        :param response: The response from the Cohere API.
        :param start_time: The start time of the request.
        :param time_elapsed: The time elapsed for the request.
        :return: A dictionary containing the parsed response and timing information.
        """
        try:
            # Each of the different endpoints map to one specific response type
            # We want to 'type check' the response without directly importing the packages type
            # It may make more sense to pass the invoked symbol from the AutologAPI instead
            response_type = str(type(response)).split("'")[1].split(".")[-1]

            # Initialize parsed_response to None to handle the case where the response type is unsupported
            parsed_response = None
            if response_type == "Generations":
                parsed_response = self._resolve_generate_response(response)
                # TODO: Remove hard-coded default model name
                table_column_order = [
                    "start_time",
                    "query_id",
                    "model",
                    "prompt",
                    "text",
                    "token_likelihoods",
                    "likelihood",
                    "time_elapsed_(seconds)",
                    "end_time",
                ]
                default_model = "command"
            elif response_type == "Chat":
                parsed_response = self._resolve_chat_response(response)
                table_column_order = [
                    "start_time",
                    "query_id",
                    "model",
                    "conversation_id",
                    "response_id",
                    "query",
                    "text",
                    "prompt",
                    "preamble",
                    "chat_history",
                    "chatlog",
                    "time_elapsed_(seconds)",
                    "end_time",
                ]
                default_model = "command"
            elif response_type == "Classifications":
                parsed_response = self._resolve_classify_response(response)
                kwargs = self._resolve_classify_kwargs(kwargs)
                table_column_order = [
                    "start_time",
                    "query_id",
                    "model",
                    "id",
                    "input",
                    "prediction",
                    "confidence",
                    "time_elapsed_(seconds)",
                    "end_time",
                ]
                default_model = "embed-english-v2.0"
            elif response_type == "SummarizeResponse":
                parsed_response = self._resolve_summarize_response(response)
                table_column_order = [
                    "start_time",
                    "query_id",
                    "model",
                    "response_id",
                    "text",
                    "additional_command",
                    "summary",
                    "time_elapsed_(seconds)",
                    "end_time",
                    "length",
                    "format",
                ]
                default_model = "summarize-xlarge"
            elif response_type == "Reranking":
                parsed_response = self._resolve_rerank_response(response)
                table_column_order = [
                    "start_time",
                    "query_id",
                    "model",
                    "id",
                    "query",
                    "top_n",
                    # This is a nested dict key that got flattened
                    "document-text",
                    "relevance_score",
                    "index",
                    "time_elapsed_(seconds)",
                    "end_time",
                ]
                default_model = "rerank-english-v2.0"
            else:
                logger.info(f"Unsupported Cohere response object: {response}")

            return self._resolve(
                args,
                kwargs,
                parsed_response,
                start_time,
                time_elapsed,
                response_type,
                table_column_order,
                default_model,
            )
        except Exception as e:
            logger.warning(f"Failed to resolve request/response: {e}")
        return None

    # These helper functions process the response from different endpoints of the Cohere API.
    # Since the response objects for different endpoints have different structures,
    # we need different logic to process them.

    def _resolve_generate_response(self, response: Response) -> List[Dict[str, Any]]:
        return_list = []
        for _response in response:
            # Built in Cohere.*.Generations function to color token_likelihoods and return a dict of response data
            _response_dict = _response._visualize_helper()
            try:
                _response_dict["token_likelihoods"] = wandb.Html(
                    _response_dict["token_likelihoods"]
                )
            except (KeyError, ValueError):
                pass
            return_list.append(_response_dict)

        return return_list

    def _resolve_chat_response(self, response: Response) -> List[Dict[str, Any]]:
        return [
            subset_dict(
                response.__dict__,
                [
                    "response_id",
                    "generation_id",
                    "query",
                    "text",
                    "conversation_id",
                    "prompt",
                    "chatlog",
                    "preamble",
                ],
            )
        ]

    def _resolve_classify_response(self, response: Response) -> List[Dict[str, Any]]:
        # The labels key is a dict returning the scores for the classification probability for each label provided
        # We flatten this nested dict for ease of consumption in the wandb UI
        return [flatten_dict(_response.__dict__) for _response in response]

    def _resolve_classify_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        # Example texts look strange when rendered in Wandb UI as it is a list of text and label
        # We extract each value into its own column
        example_texts = []
        example_labels = []
        for example in kwargs["examples"]:
            example_texts.append(example.text)
            example_labels.append(example.label)
        kwargs.pop("examples")
        kwargs["example_texts"] = example_texts
        kwargs["example_labels"] = example_labels
        return kwargs

    def _resolve_summarize_response(self, response: Response) -> List[Dict[str, Any]]:
        return [{"response_id": response.id, "summary": response.summary}]

    def _resolve_rerank_response(self, response: Response) -> List[Dict[str, Any]]:
        # The documents key contains a dict containing the content of the document which is at least "text"
        # We flatten this nested dict for ease of consumption in the wandb UI
        flattened_response_dicts = [
            flatten_dict(_response.__dict__) for _response in response
        ]
        # ReRank returns each document provided a top_n value so we aggregate into one view so users can paginate a row
        # As opposed to each row being one of the top_n responses
        return_dict = collect_common_keys(flattened_response_dicts)
        return_dict["id"] = response.id
        return [return_dict]

    def _resolve(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        parsed_response: List[Dict[str, Any]],
        start_time: float,
        time_elapsed: float,
        response_type: str,
        table_column_order: List[str],
        default_model: str,
    ) -> Dict[str, Any]:
        """Convert a list of dictionaries to a pair of column names and corresponding values, with the option to order specific dictionaries.

        :param args: The arguments passed to the API client.
        :param kwargs: The keyword arguments passed to the API client.
        :param parsed_response: The parsed response from the API.
        :param start_time: The start time of the API request.
        :param time_elapsed: The time elapsed during the API request.
        :param response_type: The type of the API response.
        :param table_column_order: The desired order of columns in the resulting table.
        :param default_model: The default model to use if not specified in the response.
        :return: A dictionary containing the formatted response.
        """
        # Args[0] is the client object where we can grab specific metadata about the underlying API status
        query_id = generate_id(length=16)
        parsed_args = subset_dict(
            args[0].__dict__,
            ["api_version", "batch_size", "max_retries", "num_workers", "timeout"],
        )

        start_time_dt = datetime.fromtimestamp(start_time)
        end_time_dt = datetime.fromtimestamp(start_time + time_elapsed)

        timings = {
            "start_time": start_time_dt,
            "end_time": end_time_dt,
            "time_elapsed_(seconds)": time_elapsed,
        }

        packed_data = []
        for _parsed_response in parsed_response:
            _packed_dict = {
                "query_id": query_id,
                **kwargs,
                **_parsed_response,
                **timings,
                **parsed_args,
            }
            if "model" not in _packed_dict:
                _packed_dict["model"] = default_model
            packed_data.append(_packed_dict)

        columns, data = reorder_and_convert_dict_list_to_table(
            packed_data, table_column_order
        )

        request_response_table = wandb.Table(data=data, columns=columns)

        return {f"{response_type}": request_response_table}
