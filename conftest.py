import pytest
import requests_mock
import os

os.environ["WANDB_DEBUG"] = "true"

#"Error: 'Session' object has no attribute 'request'""
#@pytest.fixture(autouse=True)
# def no_requests(monkeypatch):
#    monkeypatch.delattr("requests.sessions.Session.request")


@pytest.fixture
def request_mocker(request):
    """
    :param request: pytest request object for cleaning up.
    :return: Returns instance of requests mocker used to mock HTTP calls.
    """
    m = requests_mock.Mocker()
    m.start()
    request.addfinalizer(m.stop)
    return m
