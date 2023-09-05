"""Implementation of the GCP environment for wandb launch."""
import logging
import os
import re
import subprocess
from typing import Optional

from wandb.sdk.launch.errors import LaunchError
from wandb.util import get_module

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

GCS_URI_RE = re.compile(r"gs://([^/]+)/(.+)")
GCP_REGION_ENV_VAR = "GOOGLE_CLOUD_REGION"


class GcpEnvironment(AbstractEnvironment):
    """GCP Environment.

    Attributes:
        region: The GCP region.
    """

    region: str

    def __init__(self, region: str, verify: bool = True) -> None:
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
        if verify:
            self.verify()

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
                "Could not create GcpEnvironment from config. Missing 'region' "
                "field."
            )
        return cls(region=region)

    @classmethod
    def from_default(cls, verify: bool = True) -> "GcpEnvironment":
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
        return cls(region=region, verify=verify)

    @property
    def project(self) -> str:
        """Get the name of the gcp project.

        The project name is determined by the credentials, so this method
        verifies the credentials if they have not already been verified.

        Returns:
            str: The name of the gcp project.

        Raises:
            LaunchError: If the launch environment cannot be verified.
        """
        if not self._project:
            raise LaunchError(
                "This GcpEnvironment has not been verified. Please call verify() "
                "before accessing the project."
            )
        return self._project

    def get_credentials(self) -> google.auth.credentials.Credentials:  # type: ignore
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
        scopes = [
            "https://www.googleapis.com/auth/cloud-platform",
        ]
        try:
            creds, project = google.auth.default(scopes=scopes)
            if not self._project:
                self._project = project
            _logger.debug("Refreshing GCP credentials")
            creds.refresh(google.auth.transport.requests.Request())
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

    def verify(self) -> None:
        """Verify the credentials, region, and project.

        Credentials and region are verified by calling get_credentials(). The
        region and is verified by calling the compute API.

        Raises:
            LaunchError: If the credentials, region, or project are invalid.

        Returns:
            None
        """
        _logger.debug("Verifying GCP environment")
        self.get_credentials()

    def verify_storage_uri(self, uri: str) -> None:
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
        try:
            storage_client = google.cloud.storage.Client(
                credentials=self.get_credentials()
            )
            bucket = storage_client.get_bucket(bucket)
        except google.api_core.exceptions.NotFound as e:
            raise LaunchError(f"Bucket {bucket} does not exist.") from e

    def upload_file(self, source: str, destination: str) -> None:
        """Upload a file to GCS.

        Arguments:
            source: The path to the local file.
            destination: The path to the GCS file.

        Raises:
            LaunchError: If the file cannot be uploaded.
        """
        _logger.debug(f"Uploading file {source} to {destination}")
        if not os.path.isfile(source):
            raise LaunchError(f"File {source} does not exist.")
        match = GCS_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"Invalid GCS URI: {destination}")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        try:
            storage_client = google.cloud.storage.Client(
                credentials=self.get_credentials()
            )
            bucket = storage_client.bucket(bucket)
            blob = bucket.blob(key)
            blob.upload_from_filename(source)
        except google.api_core.exceptions.GoogleAPICallError as e:
            raise LaunchError(f"Could not upload file to GCS: {e}") from e

    def upload_dir(self, source: str, destination: str) -> None:
        """Upload a directory to GCS.

        Arguments:
            source: The path to the local directory.
            destination: The path to the GCS directory.

        Raises:
            LaunchError: If the directory cannot be uploaded.
        """
        _logger.debug(f"Uploading directory {source} to {destination}")
        if not os.path.isdir(source):
            raise LaunchError(f"Directory {source} does not exist.")
        match = GCS_URI_RE.match(destination)
        if not match:
            raise LaunchError(f"Invalid GCS URI: {destination}")
        bucket = match.group(1)
        key = match.group(2).lstrip("/")
        try:
            storage_client = google.cloud.storage.Client(
                credentials=self.get_credentials()
            )
            bucket = storage_client.bucket(bucket)
            for root, _, files in os.walk(source):
                for file in files:
                    local_path = os.path.join(root, file)
                    gcs_path = os.path.join(
                        key, os.path.relpath(local_path, source)
                    ).replace("\\", "/")
                    blob = bucket.blob(gcs_path)
                    blob.upload_from_filename(local_path)
        except google.api_core.exceptions.GoogleAPICallError as e:
            raise LaunchError(f"Could not upload directory to GCS: {e}") from e


def get_gcloud_config_value(config_name: str) -> Optional[str]:
    """Get a value from gcloud config.

    Arguments:
        config_name: The name of the config value.

    Returns:
        str: The config value, or None if the value is not set.
    """
    try:
        value = (
            subprocess.check_output(
                ["gcloud", "config", "get-value", config_name], stderr=subprocess.STDOUT
            )
            .decode("utf-8")
            .strip()
        )
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
