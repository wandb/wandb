import os
import shutil

import boto3
import requests

import wandb
from wandb.util import get_object_storage_headers, set_object_storage_headers

# Swith the team to use default/byob
ENTITY = "pinglei-byob-s3"
# ENTITY = "byob-test"
PROJECT = "presigned-url-header"


def upload_artifacts():
    # Upload run files (config, code) and artifacts
    with wandb.init(entity=ENTITY, project=PROJECT) as run:
        # Artifact
        artifact = wandb.Artifact("my-artifact", type="dataset")
        artifact.add_file("http-header-context.md")
        artifact.add_file("test_headers.py")
        run.log_artifact(artifact)

        # Media
        # https://docs.wandb.ai/guides/track/log/media/
        run.log({"image": wandb.Image("log_images.png")})
        # Download the video if not exists
        if not os.path.exists("butterfly.mp4"):
            response = requests.get(
                "https://flutter.github.io/assets-for-api-docs/assets/videos/butterfly.mp4"
            )
            with open("butterfly.mp4", "wb") as f:
                f.write(response.content)
        run.log({"video": wandb.Video("butterfly.mp4")})

        ## create and log table
        run.log({"table": wandb.Table(columns=["x", "y"], data=[[1, 2], [3, 4]])})

        # log metrics
        for i in range(10):
            run.log({"metric": i})


def upload_reference_file():
    # Using boto3 and pass the headers in sdk, nothing related with wandb
    def _add_headers(request, **kwargs):
        request.headers["X-My-Header-A"] = "valueA"
        request.headers["X-My-Header-B"] = "valueB"

    session = boto3.Session()
    session.events.register("before-send.s3", _add_headers)
    s3 = session.resource("s3", region_name="us-west-2")
    s3.Bucket("pinglei-byob-us-west-2").upload_file("start_proxy.sh", "start_proxy.sh")


def add_reference_artifacts():
    # NOTE: Set the s3 endpoint to the proxy
    # export AWS_S3_ENDPOINT_URL=http://localhost:8182
    with wandb.init(entity=ENTITY, project=PROJECT) as run:
        artifact = wandb.Artifact("my-reference-artifact", type="image-reference")
        artifact.add_reference(
            # NOTE: Replace this with your own s3 bucket object.
            # To get it working with the s3 file proxy, you need to use same bucket of your BYOB
            # because the proxy is hard coded to use one bucket name
            # FIXME: proxy does not work due to how aws sdk signs the request ...
            # uri="s3://uma-bucket-testing/images/apple.jpeg"
            uri="s3://pinglei-byob-us-west-2/start_proxy.sh"
        )
        run.log_artifact(artifact)


def download_reference_artifacts():
    api = wandb.Api()
    artifact = api.artifact(f"{ENTITY}/{PROJECT}/my-reference-artifact:latest")
    artifact.download(skip_cache=True)


def download_artifacts():
    # remove existing local artifacts file
    if os.path.exists("artifacts"):
        shutil.rmtree("artifacts")

    api = wandb.Api()
    artifact = api.artifact(f"{ENTITY}/{PROJECT}/my-artifact:latest")
    artifact.download(skip_cache=True)

    api = wandb.Api()
    runs = api.runs(f"{ENTITY}/{PROJECT}")
    for run in runs:
        run_id = run.id
        # downloading tables if they exist for the run
        try:
            table = api.artifact(f"{ENTITY}/{PROJECT}/run-{run_id}-table:latest")
            table.download(skip_cache=True)
            print(f"Downloaded table for run {run_id}")
        except Exception as e:
            print(f"no run table at {run_id}: {e}")


def download_run_files():
    if os.path.exists("runfiles"):
        shutil.rmtree("runfiles")

    api = wandb.Api()
    runs = api.runs(f"{ENTITY}/{PROJECT}")
    for run in runs:
        files = run.files()
        print(f"run {run.id} has {len(files)} files")
        for file in files:
            print("downloading run file", file.name)
            # NOTE: util.download_file_from_url uses https://api.wandb.ai/files/foo/bar instead of bucket url directly
            # https://api.wandb.ai/files/foo/bar redirects to https://mybucket.s3.us-west-2.amazonaws.com/foo/bar
            # API proxy need to
            # 1. replace https://api.wandb.ai/files/foo/bar with http://localhost:8181/files/foo/bar
            # 2. handle 302 redirect and replace the location header with the s3 proxy http://localhost:8182/foo/bar
            file.download(root=f"runfiles/{run.id}")

            # downloading parquet files if it exists for the run
            # note: parquet files are not guaranteed to exist for all runs immediately after the run is completed
            # it takes some time for the parquet files to be created and uploaded
            try:
                artifact = api.artifact(
                    f"{ENTITY}/{PROJECT}/run-{run.id}-history:latest"
                )
                artifact.download(skip_cache=True)
                print(f"Downloaded parquet file for run {run.id}")
            except Exception as e:
                print(f"no parquet files at {run.id}: {e}")
        # Stop after first run
        # break


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
    with set_object_storage_headers(
        {"X-My-Header-A": "valueA", "X-My-Header-B": "valueB"}
    ):
        print(get_object_storage_headers())

        # upload_artifacts()
        # print_url()
        # download_artifacts()

        upload_reference_file()
        add_reference_artifacts()
        download_reference_artifacts()

        # download_run_files()


# uv pip install -e ~/go/src/github.com/wandb/wandb
if __name__ == "__main__":
    main()
