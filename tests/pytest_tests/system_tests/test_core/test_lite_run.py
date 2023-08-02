import urllib.parse
from unittest import mock

from wandb.sdk.wandb_lite_run import InMemoryLazyLiteRun
from wandb.testing.relay import (
    DeliberateHTTPError,
    InjectedResponse,
    TokenizedCircularPattern,
)


def test_basic_lite_run(user, relay_server):
    with relay_server() as relay:
        lr = InMemoryLazyLiteRun(
            user,
            "test",
            "streamtable",
            config={"foo": "bar"},
            group="weave_stream_tables",
            _hide_in_wb=True,
        )
        lr.log({"a": 1, "b": 2, "c": 3})
        lr.finish()

    assert relay.context.history["a"][0] == 1
    assert relay.context.config["streamtable"]["foo"]["value"] == "bar"


def test_lite_run_file_stream_retry(user, relay_server, inject_file_stream_response):
    injected_response = inject_file_stream_response(
        run=mock.MagicMock(id="streamtable", project="test"),
        status=500,
        application_pattern="112",
    )
    with relay_server(inject=[injected_response]) as relay:
        lr = InMemoryLazyLiteRun(
            user,
            "test",
            "streamtable",
            config={"foo": "bar"},
            group="weave_stream_tables",
            _hide_in_wb=True,
        )
        lr.log({"a": 1, "b": 2, "c": 3})
        lr.finish()

    assert relay.context.history["a"][0] == 1


def test_lite_run_graphql_retry(
    user, relay_server, inject_file_stream_response, base_url
):
    injected_response = InjectedResponse(
        method="POST",
        url=(
            urllib.parse.urljoin(
                base_url,
                "/graphql",
            )
        ),
        body=DeliberateHTTPError(status_code=500, message="server down"),
        status=500,
        application_pattern=TokenizedCircularPattern("112"),
    )
    with relay_server(inject=[injected_response]) as relay:
        lr = InMemoryLazyLiteRun(
            user,
            "test",
            "streamtable",
            config={"foo": "bar"},
            group="weave_stream_tables",
            _hide_in_wb=True,
        )
        lr.log({"a": 1, "b": 2, "c": 3})
        lr.finish()

    assert relay.context.history["a"][0] == 1
