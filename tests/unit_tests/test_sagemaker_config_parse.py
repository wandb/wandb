from __future__ import annotations

import io
import json
import os
from unittest import mock

from wandb.integration.sagemaker.config import parse_sm_config


@mock.patch("os.path.exists")
@mock.patch("os.getenv")
@mock.patch("json.load")
@mock.patch(
    "builtins.open",
    new_callable=mock.mock_open,
    read_data=json.dumps({"param1": "2022-04-01"}),
)
def test_parse_sm_config(mock_open, mock_json_load, mock_getenv, mock_path_exists):
    """Test that the parse_sm_config function returns the correct config.

    It tests in both cases: when the SM_TRAINING_ENV environment variable is not
    set and when it is set. The function should return the correct config in both cases.
    """
    mock_getenv.return_value = "2022-07-21"
    mock_path_exists.return_value = True
    mock_file = mock.MagicMock(spec_set=io.IOBase)
    mock_file.__enter__.return_value = mock_file
    mock_open.return_value = mock_file

    mock_json_load.return_value = {
        "param1": "2022-04-01",
        "param2": "value2",
        "param3": "3",
        "param4": "-3",
        "param5": ".45",
        "param6": "-.45",
        "param7": "-0.45",
    }

    expected_conf = {
        "sagemaker_training_job_name": "2022-07-21",
        "param1": "2022-04-01",
        "param2": "value2",
        "param3": 3,
        "param4": -3,
        "param5": 0.45,
        "param6": -0.45,
        "param7": -0.45,
    }
    conf = parse_sm_config()
    # Setting the environment variable
    sm_training_env = json.dumps(
        {
            "sagemaker_training_job_name": "2022-07-21",
            "param1": "2022-04-01",
            "param2": "value2",
            "param3": "3",
            "param4": "-3",
            "param5": ".45",
            "param6": "-.45",
            "param7": "-0.45",
            "param8": True,
            "param9": None,
            "param10": 3.142,
            "param11": -3.142,
            "param12": -112358,
            "param13": ["112358", 112358, -112358, 0.1, -0.1, True, None],
            "param14": "112358",
            "param15": 112358,
            "param16": {
                "param1": "2022-04-01",
                "param2": "value2",
                "param3": "3",
                "param4": "-3",
                "param5": ".45",
                "param6": "-.45",
                "param7": "-0.45",
                "param8": True,
                "param9": None,
                "param10": 3.142,
                "param11": -3.142,
                "param12": -112358,
                "param13": ["112358", 112358, -112358, 0.1, -0.1, True, None],
                "param14": "112358",
                "param15": 112358,
                "param17": {
                    "param1": "2022-04-01",
                    "param2": "value2",
                    "param3": "3",
                    "param4": "-3",
                    "param5": ".45",
                    "param6": "-.45",
                    "param7": "-0.45",
                    "param8": True,
                    "param9": None,
                    "param10": 3.142,
                    "param11": -3.142,
                    "param12": -112358,
                    "param13": [],
                    "param14": "112358",
                    "param15": 112358,
                },
            },
        }
    )
    # Mock the environment variable
    with mock.patch.dict(
        os.environ,
        {
            "SM_TRAINING_ENV": sm_training_env,
        },
    ):
        # Mock  getenv to return the environment variable value
        mock_getenv.side_effect = lambda key, dflt=None: os.environ.get(key, dflt)
        # Deserialize it to ensure it's a valid JSON
        try:
            training_env_data = json.loads(os.getenv("SM_TRAINING_ENV"))
        except json.JSONDecodeError:
            raise AssertionError("SM_TRAINING_ENV is not a valid JSON string!")
        conf = parse_sm_config()
        expected_conf.update(training_env_data)
        assert conf == expected_conf
