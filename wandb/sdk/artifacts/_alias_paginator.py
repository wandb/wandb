"""Pagination support for `ArtifactCollectionMembership.aliasesConnection`.

Mirrors the `_ArtifactCollectionAliases` paginator in `wandb.apis.public.artifacts`,
but targets the membership-scoped connection used by `Artifact._from_name`
(backing `wandb.Api().artifact(...)` lookups) instead of the collection-scoped one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from wandb._pydantic import PaginatorVars
from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.artifacts._generated import ArtifactAliasFragment
    from wandb.sdk.artifacts._generated.artifact_membership_by_name import (
        ArtifactMembershipByNameProjectArtifactCollectionMembershipAliasesConnection,
    )
    from wandb.sdk.artifacts._models.pagination import ArtifactAliasConnection


class _MembershipAliasesVars(PaginatorVars):
    entity: str
    project: str
    name: str
    per_page: int = 1_000


class MembershipAliasesPaginator(RelayPaginator["ArtifactAliasFragment", str]):
    """Continues paginating a membership's aliases from a previous page's cursor."""

    QUERY: ClassVar[str | None] = None
    last_response: ArtifactAliasConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        entity: str,
        project: str,
        name: str,
        per_page: int = 1_000,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import ARTIFACT_MEMBERSHIP_ALIASES_GQL

            type(self).QUERY = ARTIFACT_MEMBERSHIP_ALIASES_GQL

        args = _MembershipAliasesVars(
            entity=entity, project=project, name=name, per_page=per_page
        )
        super().__init__(
            service_api,
            variables=args.model_dump(),
            per_page=args.per_page,
            start=start,
        )

    def _update_response(self) -> None:
        from wandb._strutils import nameof
        from wandb.sdk.artifacts._generated import ArtifactMembershipAliases
        from wandb.sdk.artifacts._models.pagination import ArtifactAliasConnection

        result = self._execute_query(
            parse=ArtifactMembershipAliases.model_validate_json
        )

        if not (
            (project := result.project)
            and (membership := project.artifact_collection_membership)
        ):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = ArtifactAliasConnection.model_validate(
            membership.aliases_connection
        )

    def _convert(self, node: ArtifactAliasFragment) -> str:
        return node.alias


def split_membership_aliases(
    first_page: ArtifactMembershipByNameProjectArtifactCollectionMembershipAliasesConnection,
    service_api: ServiceApi,
    *,
    entity: str,
    project: str,
    name: str,
    per_page: int = 1_000,
) -> tuple[list[str], MembershipAliasesPaginator | None]:
    """Split a membership's aliases into what's already fetched and what isn't.

    Returns `first_page`'s alias names, plus -- only if there's more --
    a paginator that lazily continues fetching the rest from its cursor.
    The caller decides whether/when it's worth paying for those extra
    requests, instead of always fetching every page up front.
    """
    aliases = [edge.node.alias for edge in first_page.edges if edge.node]

    remaining = None
    if first_page.page_info.has_next_page:
        remaining = MembershipAliasesPaginator(
            service_api,
            entity=entity,
            project=project,
            name=name,
            per_page=per_page,
            start=first_page.page_info.end_cursor,
        )

    return aliases, remaining
