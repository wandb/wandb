"""Implementation of the GCP environment for wandb launch."""

import logging
import os
import subprocess
from typing import Optional

from wandb.sdk.launch.errors import LaunchError
from wandb.util import get_module

from ..utils import GCS_URI_RE, event_loop_thread_exec
from .abstract import AbstractEnvironment

google = get_module(
    "google",
    required="Google Cloud Platform support requires the google package. Please"
    " install it with `pip install wandb[launch]`.",
)
google.cloud.compute_v1 = get_module(
    "google.cloud.compute_v1",
    required="Google Cloud Platform support requires the google-cloud-compute package. "
    "Please install it with `pip install wandb[launch]`.",
)
google.auth.credentials = get_module(
    "google.auth.credentials",
    required="Google Cloud Platform support requires google-auth. "
    "Please install it with `pip install wandb[launch]`.",
)
google.auth.transport.requests = get_module(
    "google.auth.transport.requests",
    required="Google Cloud Platform support requires google-auth. "
    "Please install it with `pip install wandb[launch]`.",
)
google.api_core.exceptions = get_module(
    "google.api_core.exceptions",
    required="Google Cloud Platform support requires google-api-core. "
    "Please install it with `pip install wandb[launch]`.",
)
google.cloud.storage = get_module(
    "google.cloud.storage",
    required="Google Cloud Platform support requires google-cloud-storage. "
    "Please install it with `pip install wandb[launch].",
)


_logger = logging.getLogger(__name__)

GCP_REGION_ENV_VAR = "GOOGLE_CLOUD_REGION"


class GcpEnvironment(AbstractEnvironment):
    """GCP Environment.

    Attributes:
        region: The GCP region.
    """

    region: str

    def __init__(
        self,
        region: str,
    ) -> None:
        """Initialize the GCP environment.

        Arguments:
            region: The GCP region.
            verify: Whether to verify the credentials, region, and project.

        Raises:
            LaunchError: If verify is True and the environment is not properly
                configured.
        """
        super().__init__()
        _logger.info(f"Initializing GcpEnvironment in region {region}")
        self.region: str = region
        self._project = ""

    @classmethod
    def from_config(cls, config: dict) -> "GcpEnvironment":
        """Create a GcpEnvironment from a config dictionary.

        Arguments:
            config: The config dictionary.

        Returns:
            GcpEnvironment: The GcpEnvironment.
        """
        if config.get("type") != "gcp":
            raise LaunchError(
                f"Could not create GcpEnvironment from config. Expected type 'gcp' "
                f"but got '{config.get('type')}'."
            )
        region = config.get("region", None)
        if not region:
            raise LaunchError(
                "Could not create GcpEnvironment from config. Missing 'region' field."
            )
        return cls(region=region)

    @classmethod
    def from_default(
        cls,
    ) -> "GcpEnvironment":
        """Create a GcpEnvironment from the default configuration.

        Returns:
            GcpEnvironment: The GcpEnvironment.
        """
        region = get_default_region()
        if region is None:
            raise LaunchError(
                "Could not create GcpEnvironment from user's gcloud configuration. "
                "Please set the default region with `gcloud config set compute/region` "
                "or set the environment variable {GCP_REGION_ENV_VAR}. "
                "Alternatively, you may specify the region explicitly in your "
                "wandb launch configuration at `$HOME/.config/wandb/launch-config.yaml`. "
                "See https://docs.wandb.ai/guides/launch/run-agent#environments for more information."
            )
        return cls(region=region)

    @property
    def project(self) -> str:
        """Get the name of the gcp project associated with the credentials.

        Returns:
            str: The name of the gcp project.

        Raises:
            LaunchError: If the launch environment cannot be verified.
        """
        return self._project

    async def get_credentials(self) -> google.auth.credentials.Credentials:  # type: ignore
        """Get the GCP credentials.

        Uses google.auth.default() to get the credentials. If the credentials
        are invalid, this method will refresh them. If the credentials are
        still invalid after refreshing, this method will raise an error.

        Returns:
            google.auth.credentials.Credentials: The GCP credentials.

        Raises:
            LaunchError: If the GCP credentials are invalid.
        """
        _logger.debug("Getting GCP credentials")
        # TODO: Figure out a minimal set of scopes.
        try:
            google_auth_default = event_loop_thread_exec(google.auth.default)
            creds, project = await google_auth_default()
            if not self._project:
                self._project = project
            _logger.debug("Refreshing GCP credentials")
            await event_loop_thread_exec(creds.refresh)(
                google.auth.transport.requests.Request()
            )
        except google.auth.exceptions.DefaultCredentialsError as e:
            raise LaunchError(
                "No Google Cloud Platform credentials found. Please run "
                "`gcloud auth application-default login` or set the environment "
                "variable GOOGLE_APPLICATION_CREDENTIALS to the path of a valid "
                "service account key file."
            ) from e
        except google.auth.exceptions.RefreshError as e:
            raise LaunchError(
                "Could not refresh Google Cloud Platform credentials. Please run "
                "`gcloud auth application-default login` or set the environment "
                "variable GOOGLE_APPLICATION_CREDENTIALS to the path of a valid "
                "service account key file."
            ) from e
        if not creds.valid:
            raise LaunchError(
                "Invalid Google Cloud Platform credentials. Please run "
                "`gcloud auth application-default login` or set the environment "
                "variable GOOGLE_APPLICATION_CREDENTIALS to the path of a valid "
                "service account key file."
            )
        return creds

    async def verify(self) -> None:
        """Verify the credentials, region, and project.

        Credentials and region are verified by calling get_credentials(). The
        region and is verified by calling the compute API.

        Raises:
            LaunchError: If the credentials, region, or project are invalid.

        Returns:
            None
        """
        _logger.debug("Verifying GCP environment")
        await self.get_credentials()

    async def verify_storage_uri(self, uri: str) -> None:
        """Verify that a storage URI is valid.

        Arguments:
            uri: The storage URI.

        Raises:
            LaunchError: If the storage URI is invalid.
        """
        match = GCS_URI_RE.match(uri)
        if not match:
            raise LaunchError(f"Invalid GCS URI: {uri}")
        bucket = match.group(1)
        cloud_storage_client = event_loop_thread_exec(google.cloud.storage.Client)
        try:
            credentials = await self.get_credentials()
            storage_client = await cloud_storage_client(credentials=credentials)
            bucket = await event_loop_thread_exec(storage_client.get_bucket)(bucket)
        except google.api_core.exceptions.GoogleAPICallError as e:
            raise LaunchError(
                f"Failed verifying storage uri {uri}: bucket {bucket} does not exist."
            ) from e
        except google.api_core.exceptions.Forbidden as e:
            raise LaunchError(
                f"Failed verifying storage uri {uri}: bucket {bucket} is not accessible. Please check your permissions and try again."
            ) from e

    async def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to GCS.

        Arguments:
            source: The path to the local file.
            destination: The path to the GCS file.

        Raises:
            LaunchError: If the file cannot be uploaded.
        """
        _logger.debug(f"Uploading file {source} to {destination}")
        _err_prefix = f"Could not upload file {source} to GCS destination {destination}"
        if not os.path.isfile(source):
            raise LaunchError(f"{_err_prefix}: File {source} does not exist.")
        match = GCS_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"{_err_prefix}: Invalid GCS URI: {destination}")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        google_storage_client = event_loop_thread_exec(google.cloud.storage.Client)
        credentials = await self.get_credentials()
        try:
            storage_client = await google_storage_client(credentials=credentials)
            bucket = await event_loop_thread_exec(storage_client.bucket)(bucket)
            blob = await event_loop_thread_exec(bucket.blob)(key)
            await event_loop_thread_exec(blob.upload_from_filename)(source)
        except google.api_core.exceptions.GoogleAPICallError as e:
            resp = e.response
            assert resp is not None
            try:
                message = resp.json()["error"]["message"]
            except Exception:
                message = str(resp)
            raise LaunchError(f"{_err_prefix}: {message}") from e

    async def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to GCS.

        Arguments:
            source: The path to the local directory.
            destination: The path to the GCS directory.

        Raises:
            LaunchError: If the directory cannot be uploaded.
        """
        _logger.debug(f"Uploading directory {source} to {destination}")
        _err_prefix = (
            f"Could not upload directory {source} to GCS destination {destination}"
        )
        if not os.path.isdir(source):
            raise LaunchError(f"{_err_prefix}: Directory {source} does not exist.")
        match = GCS_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"{_err_prefix}: Invalid GCS URI: {destination}")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        google_storage_client = event_loop_thread_exec(google.cloud.storage.Client)
        credentials = await self.get_credentials()
        try:
            storage_client = await google_storage_client(credentials=credentials)
            bucket = await event_loop_thread_exec(storage_client.bucket)(bucket)
            for root, _, files in os.walk(source):
                for file in files:
                    local_path = os.path.join(root, file)
                    gcs_path = os.path.join(
                        key, os.path.relpath(local_path, source)
                    ).replace("\\", "/")
                    blob = await event_loop_thread_exec(bucket.blob)(gcs_path)
                    await event_loop_thread_exec(blob.upload_from_filename)(local_path)
        except google.api_core.exceptions.GoogleAPICallError as e:
            resp = e.response
            assert resp is not None
            try:
                message = resp.json()["error"]["message"]
            except Exception:
                message = str(resp)
            raise LaunchError(f"{_err_prefix}: {message}") from e
        except Exception as e:
            raise LaunchError(f"{_err_prefix}: GCS upload failed: {e}") from e


def get_gcloud_config_value(config_name: str) -> Optional[str]:
    """Get a value from gcloud config.

    Arguments:
        config_name: The name of the config value.

    Returns:
        str: The config value, or None if the value is not set.
    """
    try:
        output = subprocess.check_output(
            ["gcloud", "config", "get-value", config_name], stderr=subprocess.STDOUT
        )
        value = str(output.decode("utf-8").strip())
        if value and "unset" not in value:
            return value
        return None
    except subprocess.CalledProcessError:
        return None


def get_default_region() -> Optional[str]:
    """Get the default region from gcloud config or environment variables.

    Returns:
        str: The default region, or None if it cannot be determined.
    """
    region = get_gcloud_config_value("compute/region")
    if not region:
        region = os.environ.get(GCP_REGION_ENV_VAR)
    return region
