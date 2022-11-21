from typing import Union
import urllib.parse

import pytest

import wandb
from ..conftest import InjectedResponse, DeliberateHTTPError, TokenizedCircularPattern


@pytest.fixture(scope="function")
def inject_upsert_run(base_url, user):
    def helper(
        body: Union[str, Exception] = "{'reason': 'gorilla is monkeying around'}",
        status: int = 200,
        application_pattern: str = "0",
    ) -> InjectedResponse:
        def match_upsert_run_request(_, other):
            return b"upsertBucket" in other.body

        if status > 299:
            message = body if isinstance(body, str) else "::".join(body.args)
            body = DeliberateHTTPError(status_code=status, message=message)
        return InjectedResponse(
            method="POST",
            url=(
                urllib.parse.urljoin(
                    base_url,
                    f"/graphql",
                )
            ),
            body=body,
            status=status,
            custom_match_fn=match_upsert_run_request,
            application_pattern=TokenizedCircularPattern(application_pattern),
        )

    yield helper


@pytest.mark.parametrize(
    "application_pattern",
    [
        "112",  # fail 2 times, then stop failing
    ],
)
def test_flaky_server_response(
    wandb_init,
    relay_server,
    inject_upsert_run,
    application_pattern,
    capsys,
):
    with relay_server(
        inject=[
            inject_upsert_run(
                status=409,  # see check_retry_conflict_or_gone,
                application_pattern=application_pattern,
            )
        ]
    ) as relay:
        run = wandb_init(settings=wandb.Settings(init_timeout=0.1, init_policy="async"))
        run.finish()

        captured = capsys.readouterr().err
        msg = "🐢 Communicating with wandb, run links not yet available"
        assert msg in captured
        assert len(relay.context.summary) == 1
