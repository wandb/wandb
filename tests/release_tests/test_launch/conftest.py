def pytest_addoption(parser):
    parser.addoption("--api-key")


def pytest_generate_tests(metafunc):
    option_value = metafunc.config.option.name
    if "api-key" in metafunc.fixturenames and option_value is not None:
        metafunc.parametrize("api_key", [option_value])
