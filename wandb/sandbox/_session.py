"""W&B-aware wrapper around `cwsandbox.Session`.

Most of this file exists because upstream `Session` currently hardcodes the
base `cwsandbox._sandbox.Sandbox` type in its factory and lookup paths.

If upstream exposed `self._sandbox_cls` or `_make_sandbox(...)`, plus routed
list/from_id through that class, these overrides could shrink to almost
nothing.
"""

from __future__ import annotations

from cwsandbox import Session as CWSandboxSession
from cwsandbox._defaults import DEFAULT_BASE_URL
from cwsandbox.exceptions import SandboxError

from ._sandbox import Sandbox


class Session(CWSandboxSession):
    """W&B-aware wrapper around `cwsandbox.Session`."""

    def sandbox(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        container_image: str | None = None,
        tags: list[str] | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        resources: dict | None = None,
        mounted_files: list[dict] | None = None,
        s3_mount: dict | None = None,
        ports: list[dict] | None = None,
        network=None,
        max_timeout_seconds: int | None = None,
        environment_variables: dict[str, str] | None = None,
    ) -> Sandbox:
        # Upstream instantiates the base `cwsandbox.Sandbox` here, so we need
        # a local factory override to keep returning the W&B-aware subclass.
        if self._closed:
            raise SandboxError(
                "Cannot create sandbox: session is closed. "
                "Create a new session or call sandbox() before close()."
            )

        sandbox = Sandbox(
            command=command,
            args=args,
            container_image=container_image,
            tags=tags,
            runway_ids=runway_ids,
            tower_ids=tower_ids,
            resources=resources,
            mounted_files=mounted_files,
            s3_mount=s3_mount,
            ports=ports,
            network=network,
            max_timeout_seconds=max_timeout_seconds,
            environment_variables=environment_variables,
            defaults=self._defaults,
            _session=self,
        )
        self._register_sandbox(sandbox)
        self._record_sandbox_created()
        return sandbox

    async def _list_async(
        self,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        runway_ids: list[str] | None = None,
        tower_ids: list[str] | None = None,
        include_stopped: bool = False,
        adopt: bool = False,
    ) -> list[Sandbox]:
        # Upstream `Session` routes through the base `Sandbox` class, so this
        # override keeps lookups returning the W&B-aware subclass.
        merged_tags = self._defaults.merge_tags(tags)

        if runway_ids is not None:
            effective_runway_ids = list(runway_ids)
        elif self._defaults.runway_ids:
            effective_runway_ids = list(self._defaults.runway_ids)
        else:
            effective_runway_ids = None

        if tower_ids is not None:
            effective_tower_ids = list(tower_ids)
        elif self._defaults.tower_ids:
            effective_tower_ids = list(self._defaults.tower_ids)
        else:
            effective_tower_ids = None

        sandboxes = await Sandbox._list_async(
            tags=merged_tags if merged_tags else None,
            status=status,
            runway_ids=effective_runway_ids,
            tower_ids=effective_tower_ids,
            include_stopped=include_stopped,
            base_url=None
            if self._defaults.base_url == DEFAULT_BASE_URL
            else self._defaults.base_url,
            timeout_seconds=self._defaults.request_timeout_seconds,
        )

        if adopt:
            for sandbox in sandboxes:
                self._register_sandbox(sandbox)
                sandbox._session = self

        return sandboxes

    async def _from_id_async(
        self,
        sandbox_id: str,
        *,
        adopt: bool = True,
    ) -> Sandbox:
        # Same reason as `_list_async`: keep attach/reconnect paths returning
        # the W&B-aware subclass instead of the upstream base class.
        sandbox = await Sandbox._from_id_async(
            sandbox_id,
            base_url=None
            if self._defaults.base_url == DEFAULT_BASE_URL
            else self._defaults.base_url,
            timeout_seconds=self._defaults.request_timeout_seconds,
        )

        if adopt:
            self._register_sandbox(sandbox)
            sandbox._session = self

        return sandbox
