#
# -*- coding: utf-8 -*-
"""
Utilities for wandb verify
"""
from __future__ import print_function

from functools import partial
import getpass
import os
import time
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

import click
from gql import gql  # type: ignore
from pkg_resources import parse_version  # type: ignore
import requests
import wandb

from ..wandb_artifacts import Artifact
from ...apis.internal import Api
from ...apis.public import Artifact as ArtifactAPI

PROJECT_NAME = "verify"
GET_RUN_MAX_TIME = 10
MIN_RETRYS = 3
CHECKMARK = u"\u2705"
RED_X = u"\u274C"


def print_results(
    failed_test_or_tests: Optional[Union[str, List[str]]], warning: bool
) -> None:
    if warning:
        color = "yellow"
    else:
        color = "red"
    if isinstance(failed_test_or_tests, str):
        print(RED_X)
        print(click.style(failed_test_or_tests, fg=color, bold=True))
    elif isinstance(failed_test_or_tests, list) and len(failed_test_or_tests) > 0:
        print(RED_X)
        print(
            "\n".join(
                [click.style(f, fg=color, bold=True) for f in failed_test_or_tests]
            )
        )
    else:
        print(CHECKMARK)


def check_host(host: str) -> bool:
    if host in ("api.wandb.ai", "http://api.wandb.ai", "https://api.wandb.ai"):
        print_results("Cannot run wandb verify against api.wandb.ai", False)
        return False
    return True


def check_logged_in(api: Api, host: str) -> bool:
    print("Checking if logged in".ljust(72, "."), end="")
    login_doc_url = "https://docs.wandb.ai/ref/login"
    fail_string = None
    if api.api_key is None:
        fail_string = "Not logged in. Please log in using wandb login. See the docs: {}".format(
            click.style(login_doc_url, underline=True, fg="blue")
        )
    # check that api key is correct
    # TODO: Better check for api key is correct
    else:
        res = api.api.viewer()
        if not res:
            fail_string = "Could not get viewer with default API key. Please relogin using WANDB_BASE_URL={} wandb login --relogin and try again".format(
                host
            )

    print_results(fail_string, False)
    return fail_string is None


def check_secure_requests(url: str, test_url_string: str, failure_output: str) -> None:
    # check if request is over https
    print(test_url_string.ljust(72, "."), end="")
    fail_string = None
    if not url.startswith("https"):
        fail_string = failure_output
    print_results(fail_string, True)


def check_run(api: Api) -> bool:
    print(
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

    with wandb.init(reinit=True, config=config, project=PROJECT_NAME) as run:
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
    prev_run = public_api.run("{}/{}/{}".format(entity, PROJECT_NAME, run_id))
    if prev_run is None:
        failed_test_strings.append(
            "Failed to access run through API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return False
    for key, value in prev_run.config.items():
        if config[key] != value:
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
        read_file = read_file.download(replace=True)
    except Exception:
        with wandb.init(
            reinit=True, project=PROJECT_NAME, config={"test": "test direct saving"}
        ) as run:
            saved, status_code, _ = try_manual_save(api, filepath, run.id, run.entity)
            if saved:
                failed_test_strings.append(
                    "Unable to download file. Check SQS configuration, topic configuration and bucket permissions."
                )
            else:
                failed_test_strings.append(
                    "Unable to save file with status code: {}. Check SQS configuration and bucket permissions.".format(
                        status_code
                    )
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


def try_manual_save(
    api: Api, filepath: str, run_id: str, entity: str
) -> Tuple[bool, int, Optional[str]]:

    run_id, upload_headers, result = api.api.upload_urls(
        PROJECT_NAME, [filepath], run_id, entity
    )
    extra_headers = {}
    for upload_header in upload_headers:
        key, val = upload_header.split(":", 1)
        extra_headers[key] = val

    for _, file_info in result.items():
        file_url = file_info["url"]
        # If the upload URL is relative, fill it in with the base URL,
        # since its a proxied file store like the on-prem VM.
        if file_url.startswith("/"):
            file_url = "{}{}".format(api.api.api_url, file_url)
        response = requests.put(file_url, open(filepath, "rb"), headers=extra_headers)
        break
    if response.status_code != 200:
        return False, response.status_code, response.request.url
    else:
        return True, response.status_code, response.request.url


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
    downloaded: "ArtifactAPI", computed: "ArtifactAPI", fails_list: List[str]
) -> None:
    if downloaded.digest != computed.digest:
        fails_list.append(
            "Artifact digest does not appear as expected. Contact W&B for support."
        )


def artifact_with_path_or_paths(
    name: str, verify_dir: str = None, singular: bool = False
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
    with open("{}/verify_1.txt".format(verify_dir), "w") as f:
        f.write("1")
    art.add_dir(verify_dir)
    with open("verify_3.txt", "w") as f:
        f.write("3")

    # reference to local file
    art.add_reference("file://verify_3.txt")

    return art


def log_use_download_artifact(
    artifact: "Artifact",
    alias: str,
    name: str,
    download_dir: str,
    failed_test_strings: List[str],
    add_extra_file: bool,
) -> Tuple[bool, Optional["ArtifactAPI"], List[str]]:
    with wandb.init(
        reinit=True, project=PROJECT_NAME, config={"test": "artifact log"}
    ) as log_art_run:

        if add_extra_file:
            with open("verify_2.txt", "w") as f:
                f.write("2")
                f.close()
                artifact.add_file(f.name)

        try:
            log_art_run.log_artifact(artifact, aliases=alias)
        except Exception as e:
            failed_test_strings.append("Unable to log artifact. {}".format(e))
            return False, None, failed_test_strings

    with wandb.init(
        project=PROJECT_NAME, config={"test": "artifact use"},
    ) as use_art_run:
        try:
            used_art = use_art_run.use_artifact("{}:{}".format(name, alias))
        except Exception as e:
            failed_test_strings.append("Unable to use artifact. {}".format(e))
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
    print("Checking artifact save and download workflows".ljust(72, "."), end="")
    failed_test_strings: List[str] = []

    # test checksum
    sing_art_dir = "./verify_sing_art"
    alias = "sing_art1"
    name = "sing-artys"
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
    name = "my-artys"
    art1 = artifact_with_path_or_paths(name, "./verify_art_dir", singular=False)
    cont_test, download_artifact, failed_test_strings = log_use_download_artifact(
        art1, alias, name, multi_art_dir, failed_test_strings, True
    )
    if not cont_test or download_artifact is None:
        print_results(failed_test_strings, False)
        return False
    if set(os.listdir(multi_art_dir)) != set(
        [
            "verify_a.txt",
            "verify_2.txt",
            "verify_1.txt",
            "verify_3.txt",
            "verify_int_test.txt",
        ]
    ):
        failed_test_strings.append(
            "Artifact directory is missing files. Contact W&B for support."
        )

    computed = wandb.Artifact("computed", type="dataset")
    computed.add_dir(multi_art_dir)
    verify_digest(download_artifact, computed, failed_test_strings)

    computed_manifest = computed.manifest.to_manifest_json()["contents"]
    downloaded_manifest = download_artifact._load_manifest().to_manifest_json()[
        "contents"
    ]
    verify_manifest(downloaded_manifest, computed_manifest, failed_test_strings)

    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def check_graphql_put(api: Api, host: str) -> Tuple[bool, Optional[str]]:
    # check graphql endpoint using an upload
    print("Checking signed URL upload".ljust(72, "."), end="")
    failed_test_strings = []
    gql_fp = "gql_test_file.txt"
    f = open(gql_fp, "w")
    f.write("test2")
    f.close()
    with wandb.init(
        reinit=True, project=PROJECT_NAME, config={"test": "put to graphql"}
    ) as run:
        saved, status_code, url = try_manual_save(api, gql_fp, run.id, run.entity)
        if not saved:
            print_results(
                "Server failed to accept a graphql put request with response {}. Check bucket permissions.".format(
                    status_code
                ),
                False,
            )

            # next test will also fail if this one failed. So terminate this test here.
            return False, None
    public_api = wandb.Api()
    prev_run = public_api.run("{}/{}/{}".format(run.entity, PROJECT_NAME, run.id))
    if prev_run is None:
        failed_test_strings.append(
            "Unable to access previous run through public API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return False, None
    # TODO: (kdg) refactor this so it doesn't rely on an exception handler
    try:
        read_file = retry_fn(partial(prev_run.file, gql_fp))
        read_file = read_file.download(replace=True)
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
    print(
        "Checking ability to send large payloads through proxy".ljust(72, "."), end=""
    )
    descy = "a" * int(10 ** 7)

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
        if isinstance(e, requests.HTTPError) and e.response.status_code == 413:
            failed_test_strings.append(
                'Failed to send a large payload. Check nginx.ingress.kubernetes.io/proxy-body-size is "0".'
            )
        else:
            failed_test_strings.append(
                "Failed to send a large payload with error: {}.".format(e)
            )
    print_results(failed_test_strings, False)
    return len(failed_test_strings) == 0


def check_wandb_version(api: Api) -> None:
    print("Checking wandb package version is up to date".ljust(72, "."), end="")
    _, server_info = api.viewer_server_info()
    fail_string = None
    warning = False
    max_cli_version = server_info.get("cliVersionInfo", {}).get("max_cli_version", None)
    min_cli_version = server_info.get("cliVersionInfo", {}).get("min_cli_version", None)
    if parse_version(wandb.__version__) < parse_version(min_cli_version):
        fail_string = "wandb version out of date, please run pip install --upgrade wandb=={}".format(
            max_cli_version
        )
    elif parse_version(wandb.__version__) > parse_version(max_cli_version):
        fail_string = (
            "wandb version is not supported by your local installation. This could "
            "cause some issues. If you're having problems try: please run pip "
            "install --upgrade wandb=={}".format(max_cli_version)
        )
        warning = True

    print_results(fail_string, warning)


def retry_fn(fn: Callable):
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
