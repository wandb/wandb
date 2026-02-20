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

import asyncio
import io
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from wandb_gql import gql
from wandb_gql.client import RetryError

import wandb
from wandb._strutils import nameof
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public import utils
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.apis.public.runs import Run, _server_provides_internal_id_for_project
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk import wandb_setup
from wandb.sdk.lib import asyncio_compat, retry
from wandb.sdk.lib.printer import new_printer
from wandb.sdk.lib.progress import progress_printer
from wandb.util import POW_2_BYTES, download_file_from_url, no_retry_auth, to_human_size

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb.apis.public import Api, RetryingClient

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


@dataclass(frozen=True)
class DownloadFileResult:
    """Result of a file download operation.

    Stores the outcome of attempting to download a file from W&B.
    The result can be either a successfully opened file or an exception if the
    download failed.

    Attributes:
        file: The File object that was attempted to be downloaded.
        result: Either an opened TextIOWrapper for the file on success,
            or an Exception if the download failed.
    """

    file: File
    result: io.TextIOWrapper | Exception


@dataclass
class DownloadFileTaskWrapper:
    """Wraps a File.download operation to track the time it started.

    <!-- lazydoc-ignore-init: internal -->
    """

    file: File

    def download(
        self,
        download_dir: str,
        replace: bool,
        exist_ok: bool,
        api: Api | None = None,
    ) -> DownloadFileResult:
        self.time_started = time.monotonic()
        try:
            result = self.file.download(
                root=download_dir,
                replace=replace,
                exist_ok=exist_ok,
                api=api,
            )
            return DownloadFileResult(file=self.file, result=result)
        except Exception as e:
            return DownloadFileResult(file=self.file, result=e)


class DownloadFileManager:
    """Handles downloading files in parallel and displays the progress.

    Args:
        files: List of files to download.
        download_dir: Directory in which the files should be downloaded.
        replace: Whether to replace existing files.
        exist_ok: Whether to raise an error if the file already exists.
        parallel: The number of files to download in parallel.
            If None, uses the ThreadPoolExecutor default.
        api: The API instance to use to download the files.

    <!-- lazydoc-ignore-init: internal -->
    """

    _POLL_WAIT_SECONDS = 0.1

    def __init__(
        self,
        files: list[File],
        download_dir: str,
        replace: bool,
        exist_ok: bool,
        parallel: int | None = None,
        api: Api | None = None,
    ):
        self.rate_limit_last_time: float | None = None
        self.start_time = time.monotonic()
        self.done_event = asyncio.Event()
        self.executor = ThreadPoolExecutor(max_workers=parallel)
        self.tasks: list[tuple[DownloadFileTaskWrapper, Future[DownloadFileResult]]] = [
            (
                task := DownloadFileTaskWrapper(file),
                self.executor.submit(
                    task.download,
                    download_dir,
                    replace,
                    exist_ok,
                    api=api,
                ),
            )
            for file in files
        ]

    async def wait_with_progress(self) -> list[DownloadFileResult]:
        """Wait for all files to be downloaded and return the results."""
        try:
            async with asyncio_compat.open_task_group() as group:
                group.start_soon(self._wait_then_mark_done())
                group.start_soon(self._show_progress_until_done())
            return self.results
        finally:
            self.executor.shutdown(wait=False)

    async def _wait_then_mark_done(self) -> None:
        self.results = await asyncio.gather(
            *[asyncio.wrap_future(future) for _, future in self.tasks],
        )
        self.done_event.set()

    async def _show_progress_until_done(self) -> None:
        p = new_printer()
        with progress_printer(p, "Downloading files...") as progress:
            while not await self._rate_limit_check_done():
                num_done = len([future for _, future in self.tasks if future.done()])
                progress.update(
                    pb.OperationStats(
                        operations=[
                            pb.Operation(
                                desc="downloading files",
                                progress=f"{num_done}/{len(self.tasks)} files",
                                runtime_seconds=time.monotonic() - self.start_time,
                                subtasks=[
                                    pb.Operation(
                                        desc=task.file.name,
                                        runtime_seconds=time.monotonic()
                                        - (task.time_started or time.monotonic()),
                                    )
                                    for task, future in self.tasks
                                    if future.running()
                                ],
                            )
                        ]
                    )
                )

    async def _rate_limit_check_done(self) -> bool:
        """Wait for rate limit and return whether _done is set."""
        now = time.monotonic()
        last_time = self.rate_limit_last_time
        self.rate_limit_last_time = now

        if last_time and (time_since_last := now - last_time) < self._POLL_WAIT_SECONDS:
            await asyncio_compat.race(
                asyncio.sleep(self._POLL_WAIT_SECONDS - time_since_last),
                self.done_event.wait(),
            )

        return self.done_event.is_set()


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

    def _get_query(self) -> Document:
        """Generate query dynamically based on server capabilities."""
        with_internal_id = _server_provides_internal_id_for_project(self.client)
        return gql(
            f"""#graphql
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
    def _length(self) -> int:
        """
        Returns total number of files.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            self._load_page()

        return self.last_response["project"]["run"]["fileCount"]

    @property
    def more(self) -> bool:
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
    def cursor(self) -> str | None:
        """Returns the cursor position for pagination of file results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        """Updates the GraphQL query variables for pagination.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def download_all(
        self,
        root: str = ".",
        replace: bool = False,
        exist_ok: bool = False,
        api: Api | None = None,
        parallel: int | None = None,
    ) -> list[DownloadFileResult]:
        """Downloads all files in the run to the given root directory.

        Args:
            root: The root directory to save the files.
            replace: Whether to replace existing files.
            exist_ok: Whether to raise an error if the file already exists.
            parallel: The number of files to download in parallel.
            api: The API instance to use to download the files.
        """
        files_list = list(self)
        if not files_list:
            return []

        download_manager = DownloadFileManager(
            files_list,
            download_dir=root,
            replace=replace,
            exist_ok=exist_ok,
            parallel=parallel,
            api=api,
        )
        return wandb_setup.singleton().asyncer.run(download_manager.wait_with_progress)

    def convert_objects(self) -> list[File]:
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        return [
            File(self.client, r["node"], self.run)
            for r in self.last_response["project"]["run"]["files"]["edges"]
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
        self._attrs = attrs
        self.run = run
        self.server_supports_delete_file_with_project_id: bool | None = None
        self._download_decorated: Callable[..., Any] | None = None
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

    def __repr__(self) -> str:
        classname = nameof(type(self))
        size = to_human_size(self.size, units=POW_2_BYTES)
        return f"<{classname} {self.name} ({self.mimetype}) {size}>"

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
