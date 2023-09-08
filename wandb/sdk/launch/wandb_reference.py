"""Support for parsing W&B URLs (which might be user provided) into constituent parts."""

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional
from urllib.parse import urlparse

PREFIX_HTTP = "http://"
PREFIX_HTTPS = "https://"


class ReferenceType(IntEnum):
    RUN = 1
    JOB = 2


# Ideally we would not overload the URL paths as we do.
# TODO: Not sure these are exhaustive, and even if so more special paths might get added.
#       Would be good to have restrictions that we could check.
RESERVED_NON_ENTITIES = (
    "create-team",
    "fully-connected",
    "registry",
    "settings",
    "subscriptions",
)
RESERVED_NON_PROJECTS = (
    "likes",
    "projects",
)
RESERVED_JOB_PATHS = ("_view",)


@dataclass
class WandbReference:
    # TODO: This will include port, should we separate that out?
    host: Optional[str] = None

    entity: Optional[str] = None
    project: Optional[str] = None

    # Set when we don't know how to parse yet
    path: Optional[str] = None

    # Reference type will determine what other fields are set
    ref_type: Optional[ReferenceType] = None

    run_id: Optional[str] = None

    job_name: Optional[str] = None
    job_alias: str = "latest"  # In addition to an alias can be a version specifier

    def is_bare(self) -> bool:
        return self.host is None

    def is_job(self) -> bool:
        return self.ref_type == ReferenceType.JOB

    def is_run(self) -> bool:
        return self.ref_type == ReferenceType.RUN

    def is_job_or_run(self) -> bool:
        return self.is_job() or self.is_run()

    def job_reference(self) -> str:
        assert self.is_job()
        return f"{self.job_name}:{self.job_alias}"

    def job_reference_scoped(self) -> str:
        assert self.entity
        assert self.project
        unscoped = self.job_reference()
        return f"{self.entity}/{self.project}/{unscoped}"

    def url_host(self) -> str:
        return f"{PREFIX_HTTPS}{self.host}" if self.host else ""

    def url_entity(self) -> str:
        assert self.entity
        return f"{self.url_host()}/{self.entity}"

    def url_project(self) -> str:
        assert self.project
        return f"{self.url_entity()}/{self.project}"

    @staticmethod
    def parse(uri: str) -> Optional["WandbReference"]:
        """Attempt to parse a string as a W&B URL."""
        # TODO: Error if HTTP and host is not localhost?
        if (
            not uri.startswith("/")
            and not uri.startswith(PREFIX_HTTP)
            and not uri.startswith(PREFIX_HTTPS)
        ):
            return None

        ref = WandbReference()

        # This takes care of things like query and fragment
        parsed = urlparse(uri)
        if parsed.netloc:
            ref.host = parsed.netloc

        if not parsed.path.startswith("/"):
            return ref

        ref.path = parsed.path[1:]
        parts = ref.path.split("/")
        if len(parts) > 0:
            if parts[0] not in RESERVED_NON_ENTITIES:
                ref.path = None
                ref.entity = parts[0]
                if len(parts) > 1:
                    if parts[1] not in RESERVED_NON_PROJECTS:
                        ref.project = parts[1]
                        if len(parts) > 3 and parts[2] == "runs":
                            ref.ref_type = ReferenceType.RUN
                            ref.run_id = parts[3]
                        elif (
                            len(parts) > 4
                            and parts[2] == "artifacts"
                            and parts[3] == "job"
                        ):
                            ref.ref_type = ReferenceType.JOB
                            ref.job_name = parts[4]
                            if len(parts) > 5 and parts[5] not in RESERVED_JOB_PATHS:
                                ref.job_alias = parts[5]
                        # TODO: Right now we are not tracking selection as part of URL state in the Jobs tab.
                        #       If that changes we'll want to update this.

        return ref

    @staticmethod
    def is_uri_job_or_run(uri: str) -> bool:
        ref = WandbReference.parse(uri)
        if ref and ref.is_job_or_run():
            return True
        return False
