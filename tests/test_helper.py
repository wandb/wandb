from wandb import UsageError
from wandb.sdk.wandb_helper import parse_config


def test_parse_normal_dic_config():
    config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}

    actual = parse_config(params=config_params)
    expected = config_params

    assert actual.items() == expected.items()


def test_parse_normal_dict_config_with_exclude_then_exclude_keys():
    a_dict_config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}
    a_exclude_config_params = {"a_exclude_param": 3.0}
    exclude = ["a_exclude_param"]

    config_params = a_dict_config_params.update(a_exclude_config_params)

    actual = parse_config(params=config_params, exclude=exclude)
    expected = a_dict_config_params

    assert actual.items() == expected.items()


def test_parse_normal_dict_config_with_include_then_exclude_other_keys():
    a_dict_config_params = {"a_first_parameter": 1.0, "a_second_parameter": 2.0}
    a_include_config_params = {"a_include_param": 3.0}
    include = ["a_include_param"]

    config_params = a_dict_config_params.update(a_include_config_params)

    actual = parse_config(params=config_params, include=include)
    expected = a_dict_config_params

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
