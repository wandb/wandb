from omegaconf import DictConfig

from wandb import UsageError
from wandb.sdk.wandb_helper import parse_config


def test_parse_normal_dic_config():
    config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}

    actual = parse_config(params=config_params)
    expected = config_params

    assert actual.items() == expected.items()


def test_parse_normal_dict_config_with_exclude_then_exclude_keys():
    config_params = {}
    a_dict_config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}
    a_exclude_config_params = {"a_exclude_param": 3.0}
    exclude = ["a_exclude_param"]

    config_params.update(a_dict_config_params)
    config_params.update(a_exclude_config_params)

    actual = parse_config(params=config_params, exclude=exclude)
    expected = a_dict_config_params

    assert actual.items() == expected.items()


def test_parse_normal_dict_config_with_include_then_exclude_other_keys():
    config_params = {}
    a_dict_config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}
    a_include_config_params = {"a_include_param": 3.0}
    include = ["a_include_param"]

    config_params.update(a_dict_config_params)
    config_params.update(a_include_config_params)

    actual = parse_config(params=config_params, include=include)
    expected = a_include_config_params

    assert actual.items() == expected.items()


def test_parse_normal_dict_config_with_include_and_exclude_then_raise_error():
    a_dict_config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}
    include = ["a_dummy_include"]
    exclude = ["a_dummy_exclude"]

    config_params = a_dict_config_params.update(a_dict_config_params)

    raised = False
    try:
        parse_config(params=config_params, exclude=exclude, include=include)
    except UsageError:
        raised = True
    assert raised


def test_parse_nested_dict_config():
    a_nested_dict_config = DictConfig(
        {"a_first_parameter": {"a_nested_param": 1.0}, "a_second_parameter": 2.0}
    )

    actual = parse_config(params=a_nested_dict_config)
    expected = {"a_first_parameter.a_nested_param": 1.0, "a_second_parameter": 2.0}

    assert actual.items() == expected.items()


def test_parse_nested_dict_config_with_a_list_value():
    a_nested_dict_config = DictConfig(
        {"a_first_parameter": {"a_nested_param": [1.0, 3.0]}, "a_second_parameter": 2.0}
    )

    actual = parse_config(params=a_nested_dict_config)
    expected = {
        "a_first_parameter.a_nested_param.0": 1.0,
        "a_first_parameter.a_nested_param.1": 3.0,
        "a_second_parameter": 2.0,
    }

    assert actual.items() == expected.items()
