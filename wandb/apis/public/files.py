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
from typing import TYPE_CHECKING, Any, Callable

from typing_extensions import override
from wandb_gql import gql
from wandb_gql.client import RetryError

import wandb
from wandb._strutils import nameof
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public import utils
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.apis.public.runs import Run
from wandb.apis.public.utils import gql_compat
from wandb.sdk.lib import retry
from wandb.util import POW_2_BYTES, download_file_from_url, no_retry_auth, to_human_size

if TYPE_CHECKING:
    from wandb.apis._generated import GetRunFiles
    from wandb.apis.public import Api, RetryingClient


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

    last_response: GetRunFiles | None

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

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb.apis._generated import GET_RUN_FILES_GQL, GetRunFiles

        gql_op = gql(GET_RUN_FILES_GQL)
        data = self.client.execute(gql_op, variable_values=self.variables)
        self.last_response = GetRunFiles.model_validate(data)

    @property
    @override
    def _length(self) -> int:
        """Returns total number of files.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None:
            self._load_page()
        return self.last_response.project.run.file_count

    @property
    @override
    def more(self) -> bool:
        """Returns whether there are more files to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response.project.run.files.page_info.has_next_page
        return True

    @property
    @override
    def cursor(self) -> str | None:
        """Returns the cursor position for pagination of file results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response.project.run.files.page_info.end_cursor
        return None

    @override
    def convert_objects(self) -> list[File]:
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        return [
            File(self.client, r.node.model_dump(), self.run)
            for r in self.last_response.project.run.files.edges
        ]

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
        client: The run object that contains the file
        attrs (dict): A dictionary of attributes that define the file
        run: The run object that contains the file

    <!-- lazydoc-ignore-init: internal -->
    """

    def __init__(
        self,
        client: RetryingClient,
        attrs: dict[str, Any],
        run: Run | None = None,
    ):
        self.client = client
        self.run = run
        self.server_supports_delete_file_with_project_id: bool | None = None
        self._download_decorated: Callable[..., Any] | None = None
        super().__init__(attrs)

    @property
    def size(self) -> int:
        """Returns the size of the file in bytes."""
        return 0 if (size := self._attrs.get("sizeBytes")) is None else int(size)

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

    def _build_download_wrapper(self) -> Callable[..., io.TextIOWrapper]:
        import requests

        @retry.retriable(
            retry_timedelta=RETRY_TIMEDELTA,
            check_retry_fn=no_retry_auth,
            retryable_exceptions=(RetryError, requests.RequestException),
        )
        def _impl(
            root: str = ".",
            replace: bool = False,
            exist_ok: bool = False,
            api: Api | None = None,
        ) -> io.TextIOWrapper:
            if api is None:
                api = wandb.Api()

            path = os.path.join(root, self.name)
            if os.path.exists(path) and not replace:
                if exist_ok:
                    return open(path)
                raise ValueError(
                    "File already exists, pass replace=True to overwrite "
                    "or exist_ok=True to leave it as is and don't error."
                )

            download_file_from_url(path, self.url, api.api_key)
            return open(path)

        return _impl

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
        if self._download_decorated is None:
            self._download_decorated = self._build_download_wrapper()
        return self._download_decorated(root, replace, exist_ok, api)

    @normalize_exceptions
    def delete(self) -> None:
        """Delete the file from the W&B server."""
        from wandb.apis._generated import DELETE_FILES_GQL

        variable_values = {
            "files": [self.id],
            "projectId": run._project_internal_id if (run := self.run) else None,
        }

        # Omit projectId from the mutation for older servers that don't support it.
        # GraphQL ignores extra variables in the payload when not declared in the op.
        omit_vars = (
            None if self._server_accepts_project_id_for_delete_file() else {"projectId"}
        )
        mutation = gql_compat(DELETE_FILES_GQL, omit_variables=omit_vars)
        self.client.execute(mutation, variable_values=variable_values)

    def __repr__(self) -> str:
        classname = nameof(type(self))
        size = to_human_size(self.size, units=POW_2_BYTES)
        return f"<{classname} {self.name} ({self.mimetype}) {size}>"

    @normalize_exceptions
    def _server_accepts_project_id_for_delete_file(self) -> bool:
        """Returns True if the server supports deleting files with a projectId.

        This check is done by utilizing GraphQL introspection in the available fields on the DeleteFiles API.
        """
        from wandb.apis._generated import PROBE_INPUT_FIELDS_GQL, ProbeInputFields

        # Only perform the query once to avoid extra network calls
        if self.server_supports_delete_file_with_project_id is None:
            gql_op = gql(PROBE_INPUT_FIELDS_GQL)
            gql_vars = {"type": "DeleteFilesInput"}
            data = self.client.execute(gql_op, variable_values=gql_vars)
            result = ProbeInputFields.model_validate(data)

            # If projectId is in the inputFields, the server supports deleting files with a projectId
            self.server_supports_delete_file_with_project_id = (
                (type_info := result.type_info) is not None
                and (fields := type_info.input_fields) is not None
                and any(f.name == "projectId" for f in fields)
            )

        return self.server_supports_delete_file_with_project_id
