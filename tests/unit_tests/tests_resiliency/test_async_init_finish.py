import urllib.parse
from typing import Union
from unittest import mock

import pytest
import wandb

from ..conftest import DeliberateHTTPError, InjectedResponse, TokenizedCircularPattern


@pytest.fixture(scope="function")
def inject_upsert_run(base_url, user):
    def helper(
        body: Union[str, Exception] = '{"message": "gorilla is monkeying around"}',
        status: int = 200,
        application_pattern: str = "0",
    ) -> InjectedResponse:
        def match_upsert_run_request(_, other):
            return b"upsertBucket" in other.body

        if status > 399:
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


@pytest.mark.parametrize(
    "init_timeout,finish_timeout,application_pattern,message",
    [
        # fail 2 times, then stop failing:
        (
            1e-6,
            86400,
            "112",
            "Communicating with wandb, run links not yet available",
        ),
        (
            1,
            86400,
            "11112",
            "Communicating with wandb, run links not yet available",
        ),
        # alternate between failing and not failing
        (
            1e-6,
            86400,
            "10",
            "Communicating with wandb, run links not yet available",
        ),
    ],
)
def test_flaky_server_response_init_policy_async(
    wandb_init,
    relay_server,
    inject_upsert_run,
    init_timeout,
    finish_timeout,
    application_pattern,
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
        run = wandb_init(
            settings=wandb.Settings(
                init_timeout=init_timeout,
                init_policy="async",
                finish_timeout=finish_timeout,
            )
        )
        run.finish()

        captured = capsys.readouterr().err
        assert message in captured
        assert len(relay.context.summary) == 1


@pytest.mark.parametrize(
    "init_timeout,finish_timeout,application_pattern,message",
    [
        (
            15,
            86400,
            "01112",
            "",
        ),
        (
            1e-5,
            86400,
            "110112",
            "Communicating with wandb, run links not yet available",
        ),
    ],
)
def test_flaky_server_response_init_policy_async_update_run_props(
    wandb_init,
    relay_server,
    inject_upsert_run,
    init_timeout,
    finish_timeout,
    application_pattern,
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
    ):
        run = wandb_init(
            settings=wandb.Settings(
                init_timeout=init_timeout,
                init_policy="async",
                finish_timeout=finish_timeout,
            )
        )
        run.name = "good-run"
        run.notes = "this is a good, quality run"
        run.tags = ["nice"]
        run.finish()

        captured = capsys.readouterr().err
        if message:
            assert message in captured
        # ensure that SyncStatCh thread did not get killed
        assert "SyncStatCh" not in captured


@pytest.mark.skip(
    reason="need Mailbox handle cancel PR to be merged + debug the teardown path"
)
@pytest.mark.parametrize(
    "init_timeout,finish_timeout,application_pattern,message",
    [
        # fail at init time
        (
            1e-9,
            30,
            "12",  #
            "exiting as per 'fail' init policy",
        ),
        # fail at finish time
        (
            30,
            3,
            "0" + "1" * 100,  #
            "exiting as per 'fail' finish policy",
        ),
        # always fail
        (2, 4, "1", "Error communicating with wandb process, exiting"),
    ],
)
def test_flaky_server_response_init_finish_policy_fail(
    wandb_init,
    relay_server,
    inject_upsert_run,
    init_timeout,
    finish_timeout,
    application_pattern,
    message,
    capsys,
):
    with relay_server(
        inject=[
            inject_upsert_run(
                status=500,
                application_pattern=application_pattern,
            )
        ]
    ):
        with mock.patch("os._exit", return_value="GOODBYE"):
            run = wandb_init(
                settings=wandb.Settings(
                    init_timeout=init_timeout,
                    init_policy="fail",
                    finish_timeout=finish_timeout,
                    finish_policy="fail",
                )
            )
            if run is not None:
                run.finish()

            captured = capsys.readouterr().err
            assert message in captured
