def pytest_addoption(parser):
    parser.addoption("--api-key", action="store", default=None)
    parser.addoption("--base-url", action="store", default=None)


def pytest_generate_tests(metafunc):
    api_key = metafunc.config.option.api_key
    if "api_key" in metafunc.fixturenames:
        metafunc.parametrize("api_key", [api_key])
    base_url = metafunc.config.option.base_url
    if "base_url" in metafunc.fixturenames:
        metafunc.parametrize("base_url", [base_url])
