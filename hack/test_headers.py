import os
import shutil

import wandb
from wandb.util import get_object_storage_headers, with_object_storage_headers

# Swith the team to use default/byob
# ENTITY = "pinglei-byob-s3"
ENTITY = "reg-team-2"
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


def print_url():
    api = wandb.Api()
    artifact = api.artifact(f"{ENTITY}/{PROJECT}/my-artifact:latest")

    # Fetch file URLs using the internal method
    files_page = artifact._fetch_file_urls(cursor=None, per_page=10)

    # Debug: print the type and structure
    print(f"Type of files_page: {type(files_page)}")
    print(f"files_page content: {files_page}")

    # Object response (FileUrlsFragment)
    edges = files_page.edges if hasattr(files_page, "edges") else []
    for edge in edges:
        # Access as attributes
        file_node = edge.node
        entry = artifact.get_entry(file_node.name)
        signed_url = file_node.direct_url

        print(f"\nFile: {file_node.name}")
        print(f"Entry: {entry}")
        # https://pinglei-byob-us-west-2.s3.us-west-2.amazonaws.com/wandb_artifacts/742006432/2054516011/cea0ed38c493e0b9246dffb1820bd1ef
        # https://storage.googleapis.com/wandb-artifacts-prod/wandb_artifacts/742730137/2054733236/ce745a85934553e440093c090be80aa7
        print(f"Signed URL: {signed_url}")


def main():
    # Read API key from file or environment
    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        try:
            with open("apikey.txt") as f:
                api_key = f.read().strip()
        except FileNotFoundError:
            raise ValueError("API key file not found")

    # Use the local proxy server for API
    wandb.login(host="http://localhost:8181", key=api_key)
    # Switch back to prod API to see urls before replacement by proxy
    # wandb.login(host="https://api.wandb.ai", key=api_key)
    with with_object_storage_headers(
        {"X-My-Header-A": "valueA", "X-My-Header-B": "valueB"}
    ):
        print(get_object_storage_headers())

        # upload_artifacts()
        print_url()
        # download_artifacts()
        # download_run_files()


# uv pip install -e ~/go/src/github.com/wandb/wandb
if __name__ == "__main__":
    main()
