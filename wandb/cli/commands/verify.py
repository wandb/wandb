import os
import sys
import tempfile

import click

import wandb
import wandb.sdk.verify.verify as wandb_verify
from wandb.cli.utils.api import _get_cling_api


@click.command(
    name="verify",
    context_settings={"default_map": {}},
    help="Verify your local instance",
)
@click.option("--host", default=None, help="Test a specific instance of W&B")
def verify(host):
    # TODO: (kdg) Build this all into a WandbVerify object, and clean this up.
    os.environ["WANDB_SILENT"] = "true"
    os.environ["WANDB_PROJECT"] = "verify"
    api = _get_cling_api()
    reinit = False
    if host is None:
        host = api.settings("base_url")
        print(f"Default host selected: {host}")
    # if the given host does not match the default host, re-run init
    elif host != api.settings("base_url"):
        reinit = True

    tmp_dir = tempfile.mkdtemp()
    print(
        "Find detailed logs for this test at: {}".format(os.path.join(tmp_dir, "wandb"))
    )
    os.chdir(tmp_dir)
    os.environ["WANDB_BASE_URL"] = host
    wandb.login(host=host)
    if reinit:
        api = _get_cling_api(reset=True)
    if not wandb_verify.check_host(host):
        sys.exit(1)
    if not wandb_verify.check_logged_in(api, host):
        sys.exit(1)
    url_success, url = wandb_verify.check_graphql_put(api, host)
    large_post_success = wandb_verify.check_large_post()
    wandb_verify.check_secure_requests(
        api.settings("base_url"),
        "Checking requests to base url",
        "Connections are not made over https. SSL required for secure communications.",
    )
    if url:
        wandb_verify.check_secure_requests(
            url,
            "Checking requests made over signed URLs",
            "Signed URL requests not made over https. SSL is required for secure communications.",
        )
        wandb_verify.check_cors_configuration(url, host)
    wandb_verify.check_wandb_version(api)
    check_run_success = wandb_verify.check_run(api)
    check_artifacts_success = wandb_verify.check_artifacts()
    if not (
        check_artifacts_success
        and check_run_success
        and large_post_success
        and url_success
    ):
        sys.exit(1)
