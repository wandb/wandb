"""
Utilities for wandb verify
"""

import getpass
import os
import time

import click
from gql import gql  # type: ignore
from packaging import version  # type: ignore
import requests
import wandb


if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (
        Any,
        Dict,
        List,
        Optional,
        Tuple,
        Union,
    )

    # create Artifact class with add_file method for typing
    class Artifact:
        def add_file(self, filename: str) -> None:
            pass

        def digest(self):
            pass

    from wandb.apis.internal import Api  # noqa: F401 pylint: disable=unused-import

PROJECT_NAME = "verify"
CHECKMARK = u"\u2705"
RED_X = u"\u274C"
WARNING_SIGN = u"\u1F7E1"


def print_results(
    failed_test_or_tests: Optional[Union[str, List[str]]], warning: bool
) -> None:
    if warning:
        color = "yellow"
        sign = WARNING_SIGN
    else:
        color = "red"
        sign = RED_X
    if isinstance(failed_test_or_tests, str):
        print(sign)
        print(click.style(failed_test_or_tests, fg=color, bold=True))
    elif isinstance(failed_test_or_tests, list) and len(failed_test_or_tests) > 0:
        print(sign)
        print(
            "\n".join(
                [click.style(f, fg=color, bold=True) for f in failed_test_or_tests]
            )
        )
    else:
        print(CHECKMARK)


def check_host(host: str) -> bool:
    if host == "api.wandb.ai":
        print_results("Cannot run wandb verify against api.wandb.ai", False)
        return False
    return True


def check_logged_in(api: Api) -> bool:
    # check if logged in
    print("Checking if logged in".ljust(72, "."), end="")
    login_doc_url = "https://docs.wandb.ai/ref/login"
    fail_string = None
    if api.api_key is None:
        fail_string = "Not logged in. Please log in using wandb login. See the docs: {}".format(
            click.style(login_doc_url, underline=True, fg="blue")
        )
    print_results(fail_string, False)
    return fail_string is None


def check_secure_requests(url: str, failure_output: str) -> None:
    # check if request is over https
    print("Checking requests are made over a secure connection".ljust(72, "."), end="")
    fail_string = None
    if not url.startswith("https"):
        fail_string = failure_output
    print_results(fail_string, True)


def check_run(api: Api) -> None:
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

    run = wandb.init(reinit=True, config=config)
    for i in range(1, 11):
        run.log({"loss": 1.0 / i}, step=i)
    log_dict = {"val1": 1.0, "val2": 2}
    run.log({"dict": log_dict}, step=i + 1)
    saved = True
    try:
        # this fails silently. Is there an alternative method to testing this?
        wandb.save(filepath)
    except Exception:
        saved = False
        failed_test_strings.append("There was a problem saving the file.")
    try:
        run.finish()
    except Exception:
        failed_test_strings.append("Run failed to finish. Contact W&B for support.")
        print_results(failed_test_strings, False)
        return

    time.sleep(2)
    public_api = wandb.Api()
    try:
        prev_run = public_api.run("{}/{}/{}".format(run.entity, PROJECT_NAME, run.id))
    except Exception:
        failed_test_strings.append(
            "Failed to access run through API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return
    for key, value in prev_run.config.items():
        if config[key] != value:
            failed_test_strings.append(
                "Read config values don't match run config. Check database encoding."
            )
            break
    if (
        prev_run.history_keys["keys"]["loss"]["previousValue"] != 0.1
        or prev_run.history_keys["lastStep"] != 11
        or prev_run.history_keys["keys"]["dict.val1"]["previousValue"] != 1.0
        or prev_run.history_keys["keys"]["dict.val2"]["previousValue"] != 2
    ):
        failed_test_strings.append(
            "History metrics don't match logged values. Check database encoding."
        )

    if prev_run.summary["loss"] != 1.0 / 10:
        failed_test_strings.append(
            "Read config values don't match run config. Check DB encoding."
        )
    try:
        read_file = prev_run.file(filepath).download(replace=True)
    except Exception:
        run = wandb.init(project=PROJECT_NAME, config={"test": "test direct saving"})
        saved, status_code, _ = try_manual_save(api, filepath, run.id, run.entity)
        if saved:
            failed_test_strings.append(
                "Unable to download file. Check SQS configuration, topic configuration and bucket permissions"
            )
        else:
            failed_test_strings.append(
                "Unable to save file with status code: {}. Check SQS configuration and bucket permissions".format(
                    status_code
                )
            )

        print_results(failed_test_strings, False)
        return
    contents = read_file.read()
    if contents != "test":
        failed_test_strings.append(
            "Read config values don't match run config. Contact W&B for support."
        )
    print_results(failed_test_strings, False)


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
    downloaded_manifest: Dict[str, Any], computed_manifest: Dict[str, Any], fails_list: List[str]
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
    downloaded: Artifact, computed: Artifact, fails_list: List[str]
) -> None:
    if downloaded.digest != computed.digest:
        fails_list.append(
            "Artifact digest does not appear as expected. Contact W&B for support."
        )


def check_artifacts() -> None:
    def artifact_with_path_or_paths(
        name: str, verify_dir: str = None, singular: bool = False
    ) -> Artifact:
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
        os.makedirs(verify_dir, exist_ok=True)
        with open("{}/verify_1.txt".format(verify_dir), "w") as f:
            f.write("1")
        art.add_dir(verify_dir)
        with open("verify_3.txt", "w") as f:
            f.write("3")

        # reference to local file
        art.add_reference("file://verify_3.txt")

        return art

    def log_use_download_artifact(
        artifact: Artifact,
        alias: str,
        name: str,
        download_dir: str,
        failed_test_strings: List[str],
        add_extra_file: bool,
    ) -> Tuple[bool, Optional[Artifact], List[str]]:
        log_art_run = wandb.init(project=PROJECT_NAME, config={"test": "artifact log"})

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
        try:
            log_art_run.finish()
        except Exception:
            return False, None, failed_test_strings

        use_art_run = wandb.init(
            reinit=True, project=PROJECT_NAME, config={"test": "artifact use"},
        )
        try:
            used_art = use_art_run.use_artifact("{}:{}".format(name, alias))
        except Exception as e:
            failed_test_strings.append("Unable to use artifact. {}".format(e))
            return False, None, failed_test_strings
        try:
            used_art.download(root=download_dir)
        except Exception:
            failed_test_strings.append(
                "Unable to download artifact. Check topic configuration and bucket permissions."
            )
            return False, None, failed_test_strings
        try:
            use_art_run.finish()
        except Exception:
            return False, None, failed_test_strings

        return True, used_art, failed_test_strings

    test_artifacts(artifact_with_path_or_paths, log_use_download_artifact)


def test_artifacts(artifact_with_path_or_paths, log_use_download_artifact) -> None:
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
    if not cont_test:
        print_results(failed_test_strings, False)
        return
    try:
        download_artifact.verify(root=sing_art_dir)
    except ValueError:
        failed_test_strings.append(
            "Artifact does not contain expected checksum. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )

    # test manifest and digest
    multi_art_dir = "./verify_art"
    alias = "art1"
    name = "my-artys"
    art1 = artifact_with_path_or_paths(alias, "./verify_art_dir", singular=False)
    cont_test, download_artifact, failed_test_strings = log_use_download_artifact(
        art1, alias, name, multi_art_dir, failed_test_strings, True
    )
    if not cont_test:
        print_results(failed_test_strings, False)
        return
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
            "Artifact directory is missing files. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
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


def check_graphql_put(api: Api, host: str) -> Optional[str]:
    # check graphql endpoint using an upload
    print("Checking signed URL upload".ljust(72, "."), end="")
    failed_test_strings = []
    gql_fp = "gql_test_file.txt"
    f = open(gql_fp, "w")
    f.write("test2")
    f.close()
    run = wandb.init(project=PROJECT_NAME, config={"test": "put to graphql"})
    saved, status_code, url = try_manual_save(api, gql_fp, run.id, run.entity)
    if not saved:
        print_results(
            "Server failed to accept a graphql put request with response {}. Check bucket permissions.".format(
                status_code
            ),
            False,
        )

        # next test will also fail if this one failed. So terminate this test here.
        return None
    try:
        run.finish()
    except Exception as e:
        print_results("Client failed to finish run. See the docs: {}".format(e), False)
        return None

    # wait for upload to finish before download
    time.sleep(2)

    public_api = wandb.Api()
    try:
        prev_run = public_api.run("{}/{}/{}".format(run.entity, PROJECT_NAME, run.id))
    except Exception:
        failed_test_strings.append(
            "Unable to access previous run through public API. Contact W&B for support."
        )
        print_results(failed_test_strings, False)
        return None
    try:
        read_file = prev_run.file(gql_fp).download(replace=True)
    except Exception:
        failed_test_strings.append(
            "Unable to read file successfully saved through a put request. Check SQS configurations, topic configs and SNS configs"
        )
        print_results(failed_test_strings, False)
        return None
    contents = read_file.read()
    try:
        assert contents == "test2"
    except AssertionError:
        failed_test_strings.append(
            "Read file contents do not match saved file contents. Contact W&B for support."
        )

    print_results(failed_test_strings, False)
    return url


def check_large_file(api: Api, host: str) -> None:
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
                'Failed to send a large file. Checl nginx.ingress.kubernetes.io/proxy-body-size is "0"'
            )
        else:
            failed_test_strings.append(
                "Failed to send a large file with error: {}".format(e)
            )
    print_results(failed_test_strings, False)


def check_wandb_version(api: Api) -> None:
    print("Checking wandb package version is up to date".ljust(72, "."), end="")
    fail_strings = []
    _, server_info = api.viewer_server_info()
    max_cli_version = server_info.get("cliVersionInfo", {}).get("max_cli_version", None)
    min_cli_version = server_info.get("cliVersionInfo", {}).get("min_cli_version", None)
    if version.parse(wandb.__version__) < version.parse(min_cli_version):
        fail_strings.append(
            "wandb version out of date, please run pip install --upgrade wandb=={}".format(
                max_cli_version
            )
        )
        print_results(fail_strings, False)
    elif version.parse(wandb.__version__) > version.parse(max_cli_version):
        fail_strings.append(
            "wandb version is not supported by your local installation. This could cause some issues. If you're having problems try: please run pip install --upgrade wandb=={}".format(
                max_cli_version
            )
        )
        print_results(fail_strings, True)
