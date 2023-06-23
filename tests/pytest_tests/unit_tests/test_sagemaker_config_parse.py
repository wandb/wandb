from unittest import mock

from wandb.integration.sagemaker.config import parse_sm_config


@mock.patch("os.path.exists")
@mock.patch("os.getenv")
@mock.patch("json.load")
@mock.patch("builtins.open")
def test_parse_sm_config(mock_open, mock_json_load, mock_getenv, mock_path_exists):
    mock_getenv.return_value = "2022-07-21"
    mock_path_exists.return_value = True
    mock_open.return_value = True
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

    assert conf == expected_conf
