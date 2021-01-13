import os
import requests
import time

import click
import getpass
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
from packaging import version
from typing import List, Union
import wandb
from wandb.apis.internal import Api

PROJECT_NAME = "verify"
CHECKMARK = u"\u2705"
RED_X = u"\u274C"
START_FAIL = "\033[91m" + "\033[1m"
END_FAIL = 2 * "\033[0m"


def print_results(failed_test_or_tests: Union[str, List[str]] = None) -> None:
    if isinstance(failed_test_or_tests, str):
        print(RED_X)
        print(START_FAIL + failed_test_or_tests + END_FAIL)
    elif isinstance(failed_test_or_tests, list) and len(failed_test_or_tests) > 0:
        print(RED_X)
        print(START_FAIL + "\n".join(failed_test_or_tests) + END_FAIL)
    else:
        print(CHECKMARK)


def check_host(host: str) -> bool:
    if host == "api.wandb.ai":
        print_results("Cannot run wandb verify against api.wandb.ai")
        return False
    return True


def check_logged_in(api: Api) -> bool:
    # check if logged in
    print("Checking if logged in.......", end="")
    login_doc_url = "https://docs.wandb.ai/ref/login"
    fail_string = None
    if api.api_key is None:
        fail_string = "Not logged in. Please log in using wandb login. See the docs: {}".format(
            click.style(login_doc_url, underline=True, fg="blue")
        )
    print_results(fail_string)
    return fail_string is None


def check_secure_requests(api: Api) -> None:
    # check if request is over https
    print("Checking requests are made over a secure connection.....", end="")
    response = requests.get(api.settings("base_url"))
    doc_url = "insert bad_secure_requests url here"
    try:
        assert response.request.url.startswith("https")
    except AssertionError:
        print_results(
            "Connections are not made over https. See the docs: {}".format(
                click.style(doc_url, underline=True, fg="blue")
            )
        )
    else:
        print_results()


def check_run(api: Api) -> None:
    print("Checking logged metrics, saving and downloading a file......", end="")
    failed_test_strings = []
    bad_config_url = "insert bad config url here"
    bad_history_url = "insert bad history url here"
    bad_summary_url = "insert bad summary url here"
    bad_download_file_url = "insert bad download file url here"
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
    run = wandb.init(project=PROJECT_NAME, config=config)
    for i in range(1, 11):
        run.log({"loss": 1.0 / i}, step=i)
    log_dict = {"val1": 1.0, "val2": 2}
    run.log({"dict": log_dict}, step=i + 1)
    filepath = "./test with_special-characters.txt"
    f = open(filepath, "w")
    f.write("test")
    f.close()
    try:
        wandb.save(filepath)
    except Exception:
        failed_test_strings.append(
            "There was a problem saving the file. See the docs: {}".format(
                click.style(bad_config_url, underline=True, fg="blue")
            )
        )

    run.finish()
    time.sleep(2)
    public_api = wandb.Api()
    prev_run = public_api.run("{}/{}/{}".format(run.entity, PROJECT_NAME, run.id))
    for key, value in prev_run.config.items():
        try:
            assert config[key] == value, (config[key], value)
        except AssertionError:
            failed_test_strings.append(
                "Read config values don't match run config. See the docs: {}".format(
                    click.style(bad_config_url, underline=True, fg="blue")
                )
            )
            break
    try:
        assert (
            prev_run.history_keys["keys"]["loss"]["previousValue"] == 0.1
        ), prev_run.history_keys
        assert prev_run.history_keys["lastStep"] == 11, prev_run.history_keys[
            "lastStep"
        ]
        assert (
            prev_run.history_keys["keys"]["dict.val1"]["previousValue"] == 1.0
        ), prev_run.history_keys
        assert (
            prev_run.history_keys["keys"]["dict.val2"]["previousValue"] == 2
        ), prev_run.history_keys
    except AssertionError:
        failed_test_strings.append(
            "History metrics don't match logged values. See the docs: {}".format(
                click.style(bad_history_url, underline=True, fg="blue")
            )
        )

    try:
        assert prev_run.summary["loss"] == 1.0 / 10
    except AssertionError:
        failed_test_strings.append(
            "Read config values don't match run config. See the docs: {}".format(
                click.style(bad_summary_url, underline=True, fg="blue")
            )
        )

    read_file = prev_run.file(filepath).download(replace=True)
    contents = read_file.read()
    try:
        assert (
            contents == "test"
        ), "Downloaded file contents do not match saved file. Please see..."
    except AssertionError:
        failed_test_strings.append(
            "Read config values don't match run config. See the docs: {}".format(
                click.style(bad_download_file_url, underline=True, fg="blue")
            )
        )
    print_results(failed_test_strings)


def check_artifacts() -> None:
    print("Checking artifact save and download workflows.....", end="")
    failed_test_strings = []

    def artifact_with_path_or_paths(name, singular=False):
        art = wandb.Artifact(type="artsy", name=name)

        # internal file
        with open("random.txt", "w") as f:
            f.write("test 1")
            f.close()
            art.add_file(f.name)
        if singular:
            return art

        with art.new_file("a.txt") as f:
            f.write("test 2")
        os.makedirs("./dir", exist_ok=True)
        with open("./dir/1.txt", "w") as f:
            f.write("1")
        with open("./dir/2.txt", "w") as f:
            f.write("2")
        art.add_dir("./dir")
        with open("3.txt", "w") as f:
            f.write("Test 3")

        # reference to local file
        art.add_reference("file://3.txt")

        return art

    # test checksum
    sing_art_run1 = wandb.init(project=PROJECT_NAME)
    singular_art1 = artifact_with_path_or_paths("sing-artys", True)
    sing_art_run1.log_artifact(singular_art1, aliases="sing_art1")
    sing_art_run1.finish()

    sing_art_run2 = wandb.init(reinit=True, project=PROJECT_NAME)
    sing_art2 = sing_art_run2.use_artifact("sing-artys:sing_art1")
    sing_art2.download()
    sing_art_run2.finish()

    try:
        sing_art2.verify()
    except ValueError:
        failed_test_strings.append(
            "Artifact does not contain expected checksum. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )

    # test manifest and digest
    art_run1 = wandb.init(reinit=True, project=PROJECT_NAME)
    art1 = artifact_with_path_or_paths("my-artys")
    art_run1.log_artifact(art1, aliases="art1")
    art_run1.finish()

    art_run2 = wandb.init(reinit=True, project=PROJECT_NAME)
    art2 = art_run2.use_artifact("my-artys:art1")
    art_dir = art2.download()
    art_run2.finish()

    try:
        assert set(os.listdir(art_dir)) == set(
            ["a.txt", "2.txt", "1.txt", "3.txt", "random.txt"]
        )
    except AssertionError:
        failed_test_strings.append(
            "Artifact directory is missing files. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )

    computed = wandb.Artifact("computed", type="dataset")
    computed.add_dir(art_dir)
    try:
        assert art2.digest == computed.digest
    except AssertionError:
        failed_test_strings.append(
            "Artifact digest does not appear as expected. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )
    computed_manifest = computed.manifest.to_manifest_json()["contents"]
    downloaded_manifest = art2._load_manifest().to_manifest_json()["contents"]
    try:
        for key in computed_manifest.keys():
            assert (
                computed_manifest[key]["digest"] == downloaded_manifest[key]["digest"]
            )
            assert computed_manifest[key]["size"] == downloaded_manifest[key]["size"]
    except AssertionError:
        failed_test_strings.append(
            "Artifact manifest does not appear as expected. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )

    art_run2.finish()
    print_results(failed_test_strings)


def check_graphql(api: Api, host: str) -> None:
    # check graphql endpoint using an upload
    print("Checking signed URL upload...............", end="")
    failed_test_strings = []
    gql_fp = "gql_test_file.txt"
    f = open(gql_fp, "w")
    f.write("test2")
    f.close()
    run = wandb.init(project=PROJECT_NAME)

    run_id, upload_headers, result = api.api.upload_urls(
        PROJECT_NAME, [gql_fp], run.id, run.entity
    )
    extra_headers = {}
    for upload_header in upload_headers:
        key, val = upload_header.split(":", 1)
        extra_headers[key] = val

    for file_name, file_info in result.items():
        file_url = file_info["url"]
        # If the upload URL is relative, fill it in with the base URL,
        # since its a proxied file store like the on-prem VM.
        if file_url.startswith("/"):
            file_url = "{}{}".format(api.api.api_url, file_url)
        response = requests.put(file_url, open(gql_fp, "rb"), headers=extra_headers)
        try:
            assert response.status_code == 200
        except AssertionError:
            failed_test_strings.append()
            print_results(
                "Server failed to accept a graphql put request. See the docs: {}".format(
                    click.style("PLACEHOLDER", underline=True, fg="blue")
                )
            )
            run.finish()
            # next test will also fail if this one failed. So terminate this test here.
            return
    run.finish()
    # wait for upload to finish before download
    time.sleep(2)

    public_api = wandb.Api()
    prev_run = public_api.run("{}/{}/{}".format(run.entity, PROJECT_NAME, run.id))
    read_file = prev_run.file(gql_fp).download(replace=True)
    contents = read_file.read()
    try:
        assert contents == "test2"
    except AssertionError:
        failed_test_strings.append(
            "Read file contents do not match saved file contents. See the docs: {}".format(
                click.style("PLACEHOLDER", underline=True, fg="blue")
            )
        )

    print_results(failed_test_strings)


def check_large_file(api: Api, host: str) -> None:
    print("Checking ability to send large files through proxy.....", end="")
    descy = "a" * int(10 ** 3)

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
    try:
        client = Client(
            transport=RequestsHTTPTransport(
                headers={
                    "User-Agent": api.api.user_agent,
                    "X-WANDB-USERNAME": username,
                    "X-WANDB-USER-EMAIL": None,
                },
                use_json=True,
                timeout=60,
                auth=("api", api.api_key or ""),
                url="%s/graphql" % host,
            )
        )
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
    except requests.HTTPError as e:
        if e.response.status_code == 413:
            failed_test_strings.append(
                "Failed to send a large file. See the docs: {}".format(
                    click.style("PLACEHOLDER", underline=True, fg="blue")
                )
            )
    print_results(failed_test_strings)


def wandb_version_check() -> None:
    print("Checking wandb package version is up to date.......", end="")
    response = requests.get("https://api.github.com/repos/wandb/client/releases/latest")
    fail_string = None
    if version.parse(response.json()["name"]) > version.parse(wandb.__version__):
        fail_string = (
            "wandb version out of date, please run pip install --upgrade wandb"
        )
    print_results(fail_string)
