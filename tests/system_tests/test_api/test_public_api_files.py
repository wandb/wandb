from __future__ import annotations

import pytest
import wandb


@pytest.mark.parametrize(
    "url_path",
    [
        pytest.param("files/e/p/r/50%/100%_chance.txt", id="unescaped"),
        pytest.param("files/e/p/r/50%25/100%25_chance.txt", id="escaped"),
    ],
)
def test_run_file_download_url_escaping(
    user,
    wandb_backend_spy,
    parquet_file_server,
    tmp_path,
    url_path,
):
    # The server only serves the file at the correctly escaped path, so a
    # wrongly escaped request gets a 404.
    name = "50%/100%_chance.txt"
    parquet_file_server.serve_file(
        "files/e/p/r/50%25/100%25_chance.txt",
        b"content",
    )
    with wandb.init() as run:
        pass
    api_run = wandb.Api().run(f"{run.entity}/{run.project}/{run.id}")

    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="RunFiles"),
        gql.once(
            content={
                "data": {
                    "project": {
                        "internalId": "testinternalid",
                        "run": {
                            "fileCount": 1,
                            "files": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "RmlsZToxODMw",
                                            "name": name,
                                            "url": (
                                                f"http://localhost:{parquet_file_server.port}"
                                                f"/{url_path}"
                                            ),
                                            "sizeBytes": 7,
                                        },
                                        "cursor": "cursor",
                                    },
                                ],
                                "pageInfo": {
                                    "endCursor": "cursor",
                                    "hasNextPage": False,
                                },
                            },
                        },
                    },
                },
            }
        ),
    )

    file = api_run.file(name)
    with file.download(root=str(tmp_path)) as f:
        assert f.read() == "content"
