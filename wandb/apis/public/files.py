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
from typing import TYPE_CHECKING, Any

import wandb
from wandb._strutils import nameof
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public import utils
from wandb.apis.public.runs import Run
from wandb.proto.wandb_api_pb2 import ApiRequest, DownloadFileRequest
from wandb.util import POW_2_BYTES, to_human_size

if TYPE_CHECKING:
    from wandb.apis.public import Api
    from wandb.apis.public.service_api import ServiceApi

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

    # Get the files for the run
    files = run.files()

    # Iterate over files
    for file in files:
        print(file.name)
        print(file.url)
        print(file.size)

        # Download the file
        file.download(root="download_directory", replace=True)
    ```
    """

    def _get_query(self) -> str:
        """Generate query dynamically based on server capabilities."""
        return f"""#graphql
            query RunFiles($project: String!, $entity: String!, $name: String!, $fileCursor: String,
                $fileLimit: Int = 50, $fileNames: [String] = [], $upload: Boolean = false, $pattern: String) {{
                project(name: $project, entityName: $entity) {{
                    internalId
                    run(name: $name) {{
                        fileCount
                        ...RunFilesFragment
                    }}
                }}
            }}
            {FILE_FRAGMENT}
            """

    def __init__(
        self,
        service_api: ServiceApi,
        run: Run,
        names: list[str] | None = None,
        per_page: int = 50,
        upload: bool = False,
        pattern: str | None = None,
    ):
        """Initialize a lazy iterator over a collection of `File` objects.

        Files are retrieved in pages from the W&B server as needed.

        Args:
            service_api: The service API instance to use for querying W&B.
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
        super().__init__(service_api, variables, per_page)

    def _update_response(self) -> None:
        """Fetch and store the response data for the next page using dynamic query."""
        self.last_response = self._service_api.execute_graphql(
            self._get_query(), variables=self.variables
        )

    @property
    def _length(self) -> int:
        """
        Returns total number of files.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            self._load_page()

        if not self.last_response:
            return 0

        project = self.last_response.get("project") or {}
        run_data = project.get("run") or {}
        return run_data.get("fileCount", 0)

    @property
    def more(self) -> bool:
        """Returns whether there are more files to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            return True

        project = self.last_response.get("project") or {}
        run_data = project.get("run") or {}
        files_data = run_data.get("files") or {}
        page_info = files_data.get("pageInfo") or {}
        return page_info.get("hasNextPage", False)

    @property
    def cursor(self) -> str | None:
        """Returns the cursor position for pagination of file results.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            return None

        project = self.last_response.get("project") or {}
        run_data = project.get("run") or {}
        files_data = run_data.get("files") or {}
        edges = files_data.get("edges") or []

        if not edges:
            return None

        return edges[-1].get("cursor")

    def update_variables(self) -> None:
        """Updates the GraphQL query variables for pagination.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self) -> list[File]:
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            return []

        project = self.last_response.get("project") or {}
        run_data = project.get("run") or {}
        files_data = run_data.get("files") or {}
        edges = files_data.get("edges") or []
        return [File(self._service_api, r["node"], self.run) for r in edges]

    def __repr__(self) -> str:
        return f"<{nameof(type(self))} {'/'.join(self.run.path)} ({len(self)})>"


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
        service_api: The service API instance to use for querying W&B.
        attrs (dict): A dictionary of attributes that define the file
        run: The run object that contains the file

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(
        self,
        service_api: ServiceApi,
        attrs: dict[str, Any],
        run: Run | None = None,
    ):
        self._service_api = service_api
        self._attrs = attrs
        self.run = run
        super().__init__(dict(attrs))

    @property
    def size(self) -> int:
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
        path = os.path.join(root, self.name)
        if os.path.exists(path) and not replace:
            if exist_ok:
                return open(path)
            raise ValueError(
                "File already exists, pass replace=True to overwrite "
                "or exist_ok=True to leave it as is and don't error."
            )

        service_api = api._service_api if api is not None else self._service_api
        service_api.send_api_request(
            ApiRequest(
                download_file_request=DownloadFileRequest(
                    path=path, url=self.url, size=self.size
                )
            )
        )
        return open(path)

    @normalize_exceptions
    def delete(self) -> None:
        """Delete the file from the W&B server."""
        variables = {
            "files": [self.id],
            "projectId": self.run._project_internal_id,
        }

        mutation = """
            mutation deleteFiles($files: [ID!]!, $projectId: Int) {
                deleteFiles(input: {
                    files: $files
                    projectId: $projectId
                }) {
                    success
                }
            }
        """

        self._service_api.execute_graphql(
            mutation,
            variables=variables,
        )

    def __repr__(self) -> str:
        classname = nameof(type(self))
        size = to_human_size(self.size, units=POW_2_BYTES)
        return f"<{classname} {self.name} ({self.mimetype}) {size}>"
