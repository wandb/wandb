import os

import wandb
from wandb.util import get_object_storage_headers, with_object_storage_headers

ENTITY = "pinglei-byob-s3"
PROJECT = "presigned-url-header"


def upload():
    with wandb.init(entity=ENTITY, project=PROJECT) as run:
        artifact = wandb.Artifact("my-artifact", type="dataset")
        artifact.add_file("http-header-context.md")
        artifact.add_file("test_headers.py")
        run.log_artifact(artifact)


def main():
    # Read API key from file or environment
    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        try:
            with open("apikey.txt", "r") as f:
                api_key = f.read().strip()
        except FileNotFoundError:
            raise ValueError("API key file not found")

    # TODO: use the local proxy server
    # wandb.login(host="http://localhost:8181", key=api_key)
    wandb.login(host="https://api.wandb.ai", key=api_key)
    with with_object_storage_headers(
        {"X-My-Header-A": "valueA", "X-My-Header-B": "valueB"}
    ):
        print(get_object_storage_headers())
        upload()
        # print_url()
        # download()
        # download_run_files()


# uv pip install -e ~/go/src/github.com/wandb/wandb
if __name__ == "__main__":
    main()
