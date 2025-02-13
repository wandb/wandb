"""Utilities for wandb verify."""

import contextlib
import getpass
import io
import os
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import click
import requests
from wandb_gql import gql

import wandb
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.lib import runid

from ...apis.internal import Api

PROJECT_NAME = "verify"
GET_RUN_MAX_TIME = 10
MIN_RETRYS = 3
CHECKMARK = "\u2705"
RED_X = "\u274c"
ID_PREFIX = runid.generate_id()


def nice_id(name):
    return ID_PREFIX + "-" + name


def print_results(
    failed_test_or_tests: Optional[Union[str, List[str]]], warning: bool
) -> None:
    if warning:
        color = "yellow"
    else:
        color = "red"
    if isinstance(failed_test_or_tests, str):
        print(RED_X)  # noqa: T201
        print(click.style(failed_test_or_tests, fg=color, bold=True))  # noqa: T201
    elif isinstance(failed_test_or_tests, list) and len(failed_test_or_tests) > 0:
        print(RED_X)  # noqa: T201
        print(  # noqa: T201
            "\n".join(
                [click.style(f, fg=color, bold=True) for f in failed_test_or_tests]
            )
        )
    else:
        print(CHECKMARK)  # noqa: T201


def check_host(host: str) -> bool:
    if host in ("api.wandb.ai", "http://api.wandb.ai", "https://api.wandb.ai"):
        print_results("Cannot run wandb verify against api.wandb.ai", False)
        return False
    return True


def check_logged_in(api: Api, host: str) -> bool:
    print("Checking if logged in".ljust(72, "."), end="")  # noqa: T201
    login_doc_url = "https://docs.wandb.ai/ref/cli/wandb-login"
    fail_string = None
    if api.api_key is None:
        fail_string = (
            "Not logged in. Please log in using `wandb login`. See the docs: {}".format(
                click.style(login_doc_url, underline=True, fg="blue")
            )
        )
    # check that api key is correct
    # TODO: Better check for api key is correct
    else:
        res = api.api.viewer()
        if not res:
            fail_string = (
                "Could not get viewer with default API key. "
                f"Please relogin using `WANDB_BASE_URL={host} wandb login --relogin` and try again"
            )

    print_results(fail_string, False)
    return fail_string is None


def check_secure_requests(url: str, test_url_string: str, failure_output: str) -> None:
    # check if request is over https
    print(test_url_string.ljust(72, "."), end="")  # noqa: T201
    fail_string = None
    if not url.startswith("https"):
        fail_string = failure_output
    print_results(fail_string, True)


def check_cors_configuration(url: str, origin: str) -> None:
    print("Checking CORs configuration of the bucket".ljust(72, "."), end="")  # noqa: T201
    fail_string = None
    res_get = requests.options(
        url, headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )

    if res_get.headers.get("Access-Control-Allow-Origin") is None:
        fail_string = (
            "Your object store does not have a valid CORs configuration, "
            f"you must allow GET and PUT to Origin: {origin}"
        )

    print_results(fail_string, True)


def check_run(api: Api) -> bool:
    print(  # noqa: T201
        "Checking logged metrics, saving and downloading a file".ljust(72, "."), end=""
    )
    failed_test_strings = []

    # set up config
    n_epochs = 4
    string_test = "A test config"
    dict_test = {"config_val": 2, "config_string": "config string"}
    list_test = [0, "one", "2"]
    config = {
        "epochs": n_epochs,
        "stringTest": string_test,
        "dictTest": dict_test,
        "listTest": list_test,
    }
    # create a file to save
    filepath = "./test with_special-characters.txt"
    f = open(filepath, "w")
    f.write("test")
    f.close()

    with wandb.init(
        id=nice_id("check_run"), reinit=True, config=config, project=PROJECT_NAME
    ) as run:
        run_id = run.id
        entity = run.entity
        logged = True
        try:
            for i in range(1, 11):
                run.log({"loss": 1.0 / i}, step=i)
            log_dict = {"val1": 1.0, "val2": 2}
            run.log({"dict": log_dict}, step=i + 1)
        except Exception:
            logged = False
            failed_test_strings.append(
                "Failed to log values to run. Contact W&B for support."
            )

        try:
            run.log({"HT%3ML ": wandb.Html('<a href="https://mysite">Link</a>')})
        except Exception:
            failed_test_strings.append(
                "Failed to log to media. Contact W&B for support."
            )

        wandb.save(filepath)
    public_api = wandb.Api()
    prev_run = public_api.run(f"{entity}/{PROJECT_NAME}/{run_id}")
    # raise Exception(prev_run.__dict__)
    if prev_run is None:
        failed_test_strings.append(
            "Failed to access run through API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return False
    for key, value in config.items():
        if prev_run.config.get(key) != value:
            failed_test_strings.append(
                "Read config values don't match run config. Contact W&B for support."
            )
            break
    if logged and (
        prev_run.history_keys["keys"]["loss"]["previousValue"] != 0.1
        or prev_run.history_keys["lastStep"] != 11
        or prev_run.history_keys["keys"]["dict.val1"]["previousValue"] != 1.0
        or prev_run.history_keys["keys"]["dict.val2"]["previousValue"] != 2
    ):
        failed_test_strings.append(
            "History metrics don't match logged values. Check database encoding."
        )

    if logged and prev_run.summary["loss"] != 1.0 / 10:
        failed_test_strings.append(
            "Read summary values don't match expected value. Check database encoding, or contact W&B for support."
        )
    # TODO: (kdg) refactor this so it doesn't rely on an exception handler
    try:
        read_file = retry_fn(partial(prev_run.file, filepath))
        # There's a race where the file hasn't been processed in the queue,
        # we just retry until we get a download
        read_file = retry_fn(partial(read_file.download, replace=True))
    except Exception:
        failed_test_strings.append(
            "Unable to download file. Check SQS configuration, topic configuration and bucket permissions."
        )

        print_results(failed_test_strings, False)
        return False
    contents = read_file.read()
    if contents != "test":
        failed_test_strings.append(
            "Contents of downloaded file do not match uploaded contents. Contact W&B for support."
        )
    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def verify_manifest(
    downloaded_manifest: Dict[str, Any],
    computed_manifest: Dict[str, Any],
    fails_list: List[str],
) -> None:
    try:
        for key in computed_manifest.keys():
            assert (
                computed_manifest[key]["digest"] == downloaded_manifest[key]["digest"]
            )
            assert computed_manifest[key]["size"] == downloaded_manifest[key]["size"]
    except AssertionError:
        fails_list.append(
            "Artifact manifest does not appear as expected. Contact W&B for support."
        )


def verify_digest(
    downloaded: "Artifact", computed: "Artifact", fails_list: List[str]
) -> None:
    if downloaded.digest != computed.digest:
        fails_list.append(
            "Artifact digest does not appear as expected. Contact W&B for support."
        )


def artifact_with_path_or_paths(
    name: str, verify_dir: Optional[str] = None, singular: bool = False
) -> "Artifact":
    art = wandb.Artifact(type="artsy", name=name)
    # internal file
    with open("verify_int_test.txt", "w") as f:
        f.write("test 1")
        f.close()
        art.add_file(f.name)
    if singular:
        return art
    if verify_dir is None:
        verify_dir = "./"
    with art.new_file("verify_a.txt") as f:
        f.write("test 2")
    if not os.path.exists(verify_dir):
        os.makedirs(verify_dir)
    with open(f"{verify_dir}/verify_1.txt", "w") as f:
        f.write("1")
    art.add_dir(verify_dir)
    file3 = Path(verify_dir) / "verify_3.txt"
    file3.write_text("3")

    # reference to local file
    art.add_reference(file3.resolve().as_uri())

    return art


def log_use_download_artifact(
    artifact: "Artifact",
    alias: str,
    name: str,
    download_dir: str,
    failed_test_strings: List[str],
    add_extra_file: bool,
) -> Tuple[bool, Optional["Artifact"], List[str]]:
    with wandb.init(
        id=nice_id("log_artifact"),
        reinit=True,
        project=PROJECT_NAME,
        config={"test": "artifact log"},
    ) as log_art_run:
        if add_extra_file:
            with open("verify_2.txt", "w") as f:
                f.write("2")
                f.close()
                artifact.add_file(f.name)

        try:
            log_art_run.log_artifact(artifact, aliases=alias)
        except Exception as e:
            failed_test_strings.append(f"Unable to log artifact. {e}")
            return False, None, failed_test_strings

    with wandb.init(
        id=nice_id("use_artifact"),
        project=PROJECT_NAME,
        config={"test": "artifact use"},
    ) as use_art_run:
        try:
            used_art = use_art_run.use_artifact(f"{name}:{alias}")
        except Exception as e:
            failed_test_strings.append(f"Unable to use artifact. {e}")
            return False, None, failed_test_strings
        try:
            used_art.download(root=download_dir)
        except Exception:
            failed_test_strings.append(
                "Unable to download artifact. Check bucket permissions."
            )
            return False, None, failed_test_strings

    return True, used_art, failed_test_strings


def check_artifacts() -> bool:
    print("Checking artifact save and download workflows".ljust(72, "."), end="")  # noqa: T201
    failed_test_strings: List[str] = []

    # test checksum
    sing_art_dir = "./verify_sing_art"
    alias = "sing_art1"
    name = nice_id("sing-artys")
    singular_art = artifact_with_path_or_paths(name, singular=True)
    cont_test, download_artifact, failed_test_strings = log_use_download_artifact(
        singular_art, alias, name, sing_art_dir, failed_test_strings, False
    )
    if not cont_test or download_artifact is None:
        print_results(failed_test_strings, False)
        return False
    try:
        download_artifact.verify(root=sing_art_dir)
    except ValueError:
        failed_test_strings.append(
            "Artifact does not contain expected checksum. Contact W&B for support."
        )

    # test manifest and digest
    multi_art_dir = "./verify_art"
    alias = "art1"
    name = nice_id("my-artys")
    art1 = artifact_with_path_or_paths(name, "./verify_art_dir", singular=False)
    cont_test, download_artifact, failed_test_strings = log_use_download_artifact(
        art1, alias, name, multi_art_dir, failed_test_strings, True
    )
    if not cont_test or download_artifact is None:
        print_results(failed_test_strings, False)
        return False
    if set(os.listdir(multi_art_dir)) != {
        "verify_a.txt",
        "verify_2.txt",
        "verify_1.txt",
        "verify_3.txt",
        "verify_int_test.txt",
    }:
        failed_test_strings.append(
            "Artifact directory is missing files. Contact W&B for support."
        )

    computed = wandb.Artifact("computed", type="dataset")
    computed.add_dir(multi_art_dir)
    verify_digest(download_artifact, computed, failed_test_strings)

    computed_manifest = computed.manifest.to_manifest_json()["contents"]
    downloaded_manifest = download_artifact.manifest.to_manifest_json()["contents"]
    verify_manifest(downloaded_manifest, computed_manifest, failed_test_strings)

    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def check_graphql_put(api: Api, host: str) -> Tuple[bool, Optional[str]]:
    # check graphql endpoint using an upload
    print("Checking signed URL upload".ljust(72, "."), end="")  # noqa: T201
    failed_test_strings = []
    gql_fp = "gql_test_file.txt"
    f = open(gql_fp, "w")
    f.write("test2")
    f.close()
    with wandb.init(
        id=nice_id("graphql_put"),
        reinit=True,
        project=PROJECT_NAME,
        config={"test": "put to graphql"},
    ) as run:
        wandb.save(gql_fp)
    public_api = wandb.Api()
    prev_run = public_api.run(f"{run.entity}/{PROJECT_NAME}/{run.id}")
    if prev_run is None:
        failed_test_strings.append(
            "Unable to access previous run through public API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return False, None
    # TODO: (kdg) refactor this so it doesn't rely on an exception handler
    try:
        read_file = retry_fn(partial(prev_run.file, gql_fp))
        url = read_file.url
        read_file = retry_fn(partial(read_file.download, replace=True))
    except Exception:
        failed_test_strings.append(
            "Unable to read file successfully saved through a put request. Check SQS configurations, bucket permissions and topic configs."
        )
        print_results(failed_test_strings, False)
        return False, None
    contents = read_file.read()
    try:
        assert contents == "test2"
    except AssertionError:
        failed_test_strings.append(
            "Read file contents do not match saved file contents. Contact W&B for support."
        )

    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0, url


def check_large_post() -> bool:
    print(  # noqa: T201
        "Checking ability to send large payloads through proxy".ljust(72, "."), end=""
    )
    descy = "a" * int(10**7)

    username = getpass.getuser()
    failed_test_strings = []
    query = gql(
        """
        query Project($entity: String!, $name: String!, $runName: String!, $desc: String!){
            project(entityName: $entity, name: $name) {
                run(name: $runName, desc: $desc) {
                    name
                    summaryMetrics
                }
            }
        }
        """
    )
    public_api = wandb.Api()
    client = public_api._base_client

    try:
        client._get_result(
            query,
            variable_values={
                "entity": username,
                "name": PROJECT_NAME,
                "runName": "",
                "desc": descy,
            },
            timeout=60,
        )
    except Exception as e:
        if (
            isinstance(e, requests.HTTPError)
            and e.response is not None
            and e.response.status_code == 413
        ):
            failed_test_strings.append(
                'Failed to send a large payload. Check nginx.ingress.kubernetes.io/proxy-body-size is "0".'
            )
        else:
            failed_test_strings.append(
                f"Failed to send a large payload with error: {e}."
            )
    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def check_wandb_version(api: Api) -> None:
    print("Checking wandb package version is up to date".ljust(72, "."), end="")  # noqa: T201
    _, server_info = api.viewer_server_info()
    fail_string = None
    warning = False
    max_cli_version = server_info.get("cliVersionInfo", {}).get("max_cli_version", None)
    min_cli_version = server_info.get("cliVersionInfo", {}).get(
        "min_cli_version", "0.0.1"
    )
    from wandb.util import parse_version

    if parse_version(wandb.__version__) < parse_version(min_cli_version):
        fail_string = "wandb version out of date, please run pip install --upgrade wandb=={}".format(
            max_cli_version
        )
    elif parse_version(wandb.__version__) > parse_version(max_cli_version):
        fail_string = (
            "wandb version is not supported by your local installation. This could "
            "cause some issues. If you're having problems try: please run `pip "
            f"install --upgrade wandb=={max_cli_version}`"
        )
        warning = True

    print_results(fail_string, warning)


def check_sweeps(api: Api) -> bool:
    print("Checking sweep creation and agent execution".ljust(72, "."), end="")  # noqa: T201
    failed_test_strings: List[str] = []

    sweep_config = {
        "method": "random",
        "metric": {"goal": "minimize", "name": "score"},
        "parameters": {
            "x": {"values": [0.01, 0.05, 0.1]},
            "y": {"values": [1, 2, 3]},
        },
        "name": "verify_sweep",
    }

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sweep_id = wandb.sweep(
                sweep=sweep_config, project=PROJECT_NAME, entity=api.default_entity
            )
    except Exception as e:
        failed_test_strings.append(f"Failed to create sweep: {e}")
        print_results(failed_test_strings, False)
        return False

    if not sweep_id:
        failed_test_strings.append("Sweep creation returned an invalid ID.")
        print_results(failed_test_strings, False)
        return False

    try:

        def objective(config):
            score = config.x**3 + config.y
            return score

        def main():
            with wandb.init(project=PROJECT_NAME) as run:
                score = objective(run.config)
                run.log({"score": score})

        wandb.agent(sweep_id, function=main, count=10)
    except Exception as e:
        failed_test_strings.append(f"Failed to run sweep agent: {e}")
        print_results(failed_test_strings, False)
        return False

    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def retry_fn(fn: Callable) -> Any:
    ini_time = time.time()
    res = None
    i = 0
    while i < MIN_RETRYS or time.time() - ini_time < GET_RUN_MAX_TIME:
        i += 1
        try:
            res = fn()
            break
        except Exception:
            time.sleep(1)
            continue
    return res
