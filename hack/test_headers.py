import os
import shutil

import wandb
from wandb.util import get_object_storage_headers, with_object_storage_headers

# TODO: allow switching to non byob to make it easier for other people to test.
ENTITY = "pinglei-byob-s3"
PROJECT = "presigned-url-header"


# TODO: log media
def upload_artifacts():
    # Upload run files (config, code) and artifacts
    with wandb.init(entity=ENTITY, project=PROJECT) as run:
        artifact = wandb.Artifact("my-artifact", type="dataset")
        artifact.add_file("http-header-context.md")
        artifact.add_file("test_headers.py")
        run.log_artifact(artifact)


def download_artifacts():
    # remove existing local artifacts file
    if os.path.exists("artifacts"):
        shutil.rmtree("artifacts")

    api = wandb.Api()
    artifact = api.artifact(f"{ENTITY}/{PROJECT}/my-artifact:latest")
    artifact.download(skip_cache=True)


def download_run_files():
    if os.path.exists("runfiles"):
        shutil.rmtree("runfiles")

    api = wandb.Api()
    # FIXME: replace it with your run id
    run = api.run(f"{ENTITY}/{PROJECT}/ubf0qbn9")
    files = run.files()
    for file in files:
        print("downloading run file", file.name)
        # NOTE: util.download_file_from_url uses https://api.wandb.ai/files/foo/bar instead of bucket url directly
        # https://api.wandb.ai/files/foo/bar redirects to https://mybucket.s3.us-west-2.amazonaws.com/foo/bar
        # API proxy need to
        # 1. replace https://api.wandb.ai/files/foo/bar with http://localhost:8181/files/foo/bar
        # 2. handle 302 redirect and replace the location header with the s3 proxy http://localhost:8182/foo/bar
        file.download(root="runfiles")


def main():
    # Read API key from file or environment
    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        try:
            with open("apikey.txt", "r") as f:
                api_key = f.read().strip()
        except FileNotFoundError:
            raise ValueError("API key file not found")

    # Use the local proxy server for API
    wandb.login(host="http://localhost:8181", key=api_key)
    # wandb.login(host="https://api.wandb.ai", key=api_key)
    with with_object_storage_headers(
        {"X-My-Header-A": "valueA", "X-My-Header-B": "valueB"}
    ):
        print(get_object_storage_headers())

        # upload_artifacts() # pass
        # download_artifacts() # pass
        download_run_files()


# uv pip install -e ~/go/src/github.com/wandb/wandb
if __name__ == "__main__":
    main()
