import sys
import urllib.parse
from typing import Union

import pytest
import wandb

from ..conftest import DeliberateHTTPError, InjectedResponse, TokenizedCircularPattern


if sys.version_info >= (3, 7):
    from contextlib import nullcontext


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
                    "/graphql",
                )
            ),
            body=body,
            status=status,
            custom_match_fn=match_upsert_run_request,
            application_pattern=TokenizedCircularPattern(application_pattern),
        )

    yield helper


# skip on py3.6
@pytest.mark.timeout(15)
@pytest.mark.skipif(
    sys.version_info < (3, 7), reason="nullcontext not supported in py3.6"
)
@pytest.mark.parametrize(
    "init_timeout,init_policy,finish_timeout,application_pattern,should_fail,message",
    [
        # fail 2 times, then stop failing:
        (
            1e-6,
            "async",
            86400,
            "112",
            False,
            "🐢 Communicating with wandb, run links not yet available",
        ),
        # alternate between failing and not failing
        (
            1e-6,
            "async",
            86400,
            "10",
            False,
            "🐢 Communicating with wandb, run links not yet available",
        ),
        # always fail, longer than the timeout
        (2, "fail", 4, "1", True, "Error communicating with wandb process, exiting"),
    ],
)
def test_flaky_server_response(
    wandb_init,
    relay_server,
    inject_upsert_run,
    init_timeout,
    init_policy,
    finish_timeout,
    application_pattern,
    should_fail,
    message,
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
        with pytest.raises(Exception) if should_fail else nullcontext():
            run = wandb_init(
                settings=wandb.Settings(
                    init_timeout=init_timeout,
                    init_policy=init_policy,
                    finish_timeout=finish_timeout,
                )
            )
            if not should_fail:
                run.finish()

            captured = capsys.readouterr().err
            if message:
                assert message in captured
                assert len(relay.context.summary) == 1
