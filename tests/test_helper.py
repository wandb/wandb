import argparse

from absl import flags
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


def test_parse_empty_dict():
    config_params = {}

    actual = parse_config(params=config_params)
    expected = config_params

    assert actual.items() == expected.items()


def test_parse_dict_not_a_dict_config_then_raise_error():
    not_a_dict_config = ["a_list"]

    raised = False
    try:
        parse_config(params=not_a_dict_config)
    except TypeError:
        raised = True
    assert raised


def test_parse_dict_of_tensorflow_flags():
    flags.DEFINE_string("a_flag", "a_value", "a help message")
    flags.DEFINE_integer("another_flag", 1, "a definition of a flag")

    actual = parse_config(params=flags.FLAGS)

    expected = {"a_flag": "a_value", "another_flag": 1}

    # Since flags also generated other params, we only focuses on those we have set
    for key, expected_value in expected.items():
        # We use get, then if key not there will return a none and test fail
        actual_value = actual.get(key)
        assert actual_value == expected_value


def test_parse_dict_an_argparse_namespace():
    parser = argparse.ArgumentParser()
    parser.add_argument("an_argument", type=str)

    args = parser.parse_args(["a_value_for_the_argument"])
    actual = parse_config(params=args)

    expected = {"an_argument": "a_value_for_the_argument"}

    assert actual.items() == expected.items()


def test_parse_omegaconf_dict_into_primitive_dict():
    a_nested_dict_config = DictConfig(
        {"a_first_parameter": {"a_nested_param": 1.0}, "a_second_parameter": 2.0}
    )
    assert not isinstance(a_nested_dict_config, dict)

    actual = parse_config(params=a_nested_dict_config)
    expected = {"a_first_parameter": {"a_nested_param": 1.0}, "a_second_parameter": 2.0}

    assert actual.items() == expected.items()
    assert isinstance(actual, dict)


def test_parse_complex_omegaconf_dict_into_primitive_dict():
    a_nested_dict_config = DictConfig(
        {"a_first_parameter": {"a_nested_param": [1.0, 3.0]}, "a_second_parameter": 2.0}
    )
    assert not isinstance(a_nested_dict_config, dict)

    actual = parse_config(params=a_nested_dict_config)
    expected = {"a_first_parameter": {"a_nested_param": [1.0, 3.0]}, "a_second_parameter": 2.0}

    assert actual.items() == expected.items()
    assert isinstance(actual, dict)


def test_parse_omegaconf_dict_with_resolve_into_primitive_dict():
    a_nested_dict_config = DictConfig(
        {'foo': 'bar', 'foo2': '${foo}'}
    )
    assert not isinstance(a_nested_dict_config, dict)

    actual = parse_config(params=a_nested_dict_config)
    expected = {'foo': 'bar', 'foo2': 'bar'}

    assert actual.items() == expected.items()
    assert isinstance(actual, dict)
