"""W&B Public API for File objects.

This module provides classes for interacting with files stored in W&B.

Example:
```python
from wandb.apis.public import Api

# Get files from a specific run
run = Api().run("entity/project/run_id")
files = run.files()

# Work with files
for file in files:
    print(f"File: {file.name}")
    print(f"Size: {file.size} bytes")
    print(f"Type: {file.mimetype}")

    # Download file
    if file.size < 1000000:  # Less than 1MB
        file.download(root="./downloads")

    # Get S3 URI for large files
    if file.size >= 1000000:
        print(f"S3 URI: {file.path_uri}")
```

Note:
    This module is part of the W&B Public API and provides methods to access,
    download, and manage files stored in W&B. Files are typically associated
    with specific runs and can include model weights, datasets, visualizations,
    and other artifacts.
"""

from __future__ import annotations

import io
import os

import requests
from wandb_gql import gql
from wandb_gql.client import RetryError

import wandb
from wandb import util
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public import utils
from wandb.apis.public.api import Api, RetryingClient
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.apis.public.runs import Run, _server_provides_internal_id_for_project
from wandb.sdk.lib import retry

FILE_FRAGMENT = """fragment RunFilesFragment on Run {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit, pattern: $pattern) {
        edges {
            node {
                id
                name
                url(upload: $upload)
                directUrl
                sizeBytes
                mimetype
                updatedAt
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""


class Files(SizedPaginator["File"]):
    """A lazy iterator over a collection of `File` objects.

    Access and manage files uploaded to W&B during a run. Handles pagination
    automatically when iterating through large collections of files.

    Example:
    ```python
    from wandb.apis.public.files import Files
    from wandb.apis.public.api import Api

    # Example run object
    run = Api().run("entity/project/run-id")

    # Create a Files object to iterate over files in the run
    files = Files(api.client, run)

    # Iterate over files
    for file in files:
        print(file.name)
        print(file.url)
        print(file.size)

        # Download the file
        file.download(root="download_directory", replace=True)
    ```
    """

    def _get_query(self):
        """Generate query dynamically based on server capabilities."""
        with_internal_id = _server_provides_internal_id_for_project(self.client)
        return gql(
            f"""
            query RunFiles($project: String!, $entity: String!, $name: String!, $fileCursor: String,
                $fileLimit: Int = 50, $fileNames: [String] = [], $upload: Boolean = false, $pattern: String) {{
                project(name: $project, entityName: $entity) {{
                    {"internalId" if with_internal_id else ""}
                    run(name: $name) {{
                        fileCount
                        ...RunFilesFragment
                    }}
                }}
            }}
            {FILE_FRAGMENT}
            """
        )

    def __init__(
        self,
        client: RetryingClient,
        run: Run,
        names: list[str] | None = None,
        per_page: int = 50,
        upload: bool = False,
        pattern: str | None = None,
    ):
        """Initialize a lazy iterator over a collection of `File` objects.

        Files are retrieved in pages from the W&B server as needed.

        Args:
            client: The run object that contains the files
            run: The run object that contains the files
            names (list, optional): A list of file names to filter the files
            per_page (int, optional): The number of files to fetch per page
            upload (bool, optional): If `True`, fetch the upload URL for each file
            pattern (str, optional): Pattern to match when returning files from W&B
                This pattern uses mySQL's LIKE syntax,
                so matching all files that end with .json would be "%.json".
                If both names and pattern are provided, a ValueError will be raised.
        """
        if names and pattern:
            raise ValueError(
                "Querying for files by both names and pattern is not supported."
                " Please provide either a list of names or a pattern to match.",
            )

        self.run = run
        variables = {
            "project": run.project,
            "entity": run.entity,
            "name": run.id,
            "fileNames": names or [],
            "upload": upload,
            "pattern": pattern,
        }
        super().__init__(client, variables, per_page)

    def _update_response(self) -> None:
        """Fetch and store the response data for the next page using dynamic query."""
        self.last_response = self.client.execute(
            self._get_query(), variable_values=self.variables
        )

    @property
    def _length(self):
        """
        Returns total number of files.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            self._load_page()

        return self.last_response["project"]["run"]["fileCount"]

    @property
    def more(self):
        """Returns whether there are more files to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        """Returns the cursor position for pagination of file results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        """Updates the GraphQL query variables for pagination.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self):
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        return [
            File(self.client, r["node"], self.run)
            for r in self.last_response["project"]["run"]["files"]["edges"]
        ]

    def __repr__(self):
        return "<Files {} ({})>".format("/".join(self.run.path), len(self))


class File(Attrs):
    """File saved to W&B.

    Represents a single file stored in W&B. Includes access to file metadata.
    Files are associated with a specific run and
    can include text files, model weights, datasets, visualizations, and other
    artifacts. You can download the file, delete the file, and access file
    properties.

    Specify one or more attributes in a dictionary to fine a specific
    file logged to a specific run. You can search using the following keys:

    - id (str): The ID of the run that contains the file
    - name (str): Name of the file
    - url (str): path to file
    - direct_url (str): path to file in the bucket
    - sizeBytes (int): size of file in bytes
    - md5 (str): md5 of file
    - mimetype (str): mimetype of file
    - updated_at (str): timestamp of last update
    - path_uri (str): path to file in the bucket, currently only available for S3 objects and reference files

    Args:
        client: The run object that contains the file
        attrs (dict): A dictionary of attributes that define the file
        run: The run object that contains the file

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(self, client, attrs, run=None):
        self.client = client
        self._attrs = attrs
        self.run = run
        self.server_supports_delete_file_with_project_id: bool | None = None
        super().__init__(dict(attrs))

    @property
    def size(self):
        """Returns the size of the file in bytes."""
        size_bytes = self._attrs["sizeBytes"]
        if size_bytes is not None:
            return int(size_bytes)
        return 0

    @property
    def path_uri(self) -> str:
        """Returns the URI path to the file in the storage bucket.

        Returns:
            str: The S3 URI (e.g., 's3://bucket/path/to/file') if the file is stored in S3,
                 the direct URL if it's a reference file, or an empty string if unavailable.
        """
        if not (direct_url := self._attrs.get("directUrl")):
            wandb.termwarn("Unable to find direct_url of file")
            return ""

        # For reference files, both the directUrl and the url are just the path to the file in the bucket
        if direct_url == self._attrs.get("url"):
            return direct_url

        try:
            return utils.parse_s3_url_to_s3_uri(direct_url)
        except ValueError:
            wandb.termwarn("path_uri is only available for files stored in S3")
            return ""

    @normalize_exceptions
    @retry.retriable(
        retry_timedelta=RETRY_TIMEDELTA,
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def download(
        self,
        root: str = ".",
        replace: bool = False,
        exist_ok: bool = False,
        api: Api | None = None,
    ) -> io.TextIOWrapper:
        """Downloads a file previously saved by a run from the wandb server.

        Args:
            root: Local directory to save the file. Defaults to the
                current working directory (".").
            replace: If `True`, download will overwrite a local file
                if it exists. Defaults to `False`.
            exist_ok: If `True`, will not raise ValueError if file already
                exists and will not re-download unless replace=True.
                Defaults to `False`.
            api: If specified, the `Api` instance used to download the file.

        Raises:
            `ValueError` if file already exists, `replace=False` and
            `exist_ok=False`.
        """
        if api is None:
            api = wandb.Api()

        path = os.path.join(root, self.name)
        if os.path.exists(path) and not replace:
            if exist_ok:
                return open(path)
            else:
                raise ValueError(
                    "File already exists, pass replace=True to overwrite or exist_ok=True to leave it as is and don't error."
                )

        util.download_file_from_url(path, self.url, api.api_key)
        return open(path)

    @normalize_exceptions
    def delete(self):
        """Delete the file from the W&B server."""
        project_id_mutation_fragment = ""
        project_id_variable_fragment = ""
        variable_values = {
            "files": [self.id],
        }

        # Add projectId to mutation and variables if the server supports it.
        # Otherwise, do not include projectId in mutation for older server versions which do not support it.
        if self._server_accepts_project_id_for_delete_file():
            variable_values["projectId"] = self.run._project_internal_id
            project_id_variable_fragment = ", $projectId: Int"
            project_id_mutation_fragment = "projectId: $projectId"

        mutation_string = """
            mutation deleteFiles($files: [ID!]!{}) {{
                deleteFiles(input: {{
                    files: $files
                    {}
                }}) {{
                    success
                }}
            }}
            """.format(project_id_variable_fragment, project_id_mutation_fragment)
        mutation = gql(mutation_string)

        self.client.execute(
            mutation,
            variable_values=variable_values,
        )

    def __repr__(self):
        return "<File {} ({}) {}>".format(
            self.name,
            self.mimetype,
            util.to_human_size(self.size, units=util.POW_2_BYTES),
        )

    @normalize_exceptions
    def _server_accepts_project_id_for_delete_file(self) -> bool:
        """Returns True if the server supports deleting files with a projectId.

        This check is done by utilizing GraphQL introspection in the available fields on the DeleteFiles API.
        """
        query_string = """
           query ProbeDeleteFilesProjectIdInput {
                DeleteFilesProjectIdInputType: __type(name:"DeleteFilesInput") {
                    inputFields{
                        name
                    }
                }
            }
        """

        # Only perform the query once to avoid extra network calls
        if self.server_supports_delete_file_with_project_id is None:
            query = gql(query_string)
            res = self.client.execute(query)

            # If projectId is in the inputFields, the server supports deleting files with a projectId
            self.server_supports_delete_file_with_project_id = "projectId" in [
                x["name"]
                for x in (
                    res.get("DeleteFilesProjectIdInputType", {}).get(
                        "inputFields", [{}]
                    )
                )
            ]

        return self.server_supports_delete_file_with_project_id
