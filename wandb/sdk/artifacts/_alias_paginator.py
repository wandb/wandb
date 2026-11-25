"""Pagination support for `ArtifactCollectionMembership.aliasesConnection`.

Mirrors the `_ArtifactCollectionAliases` paginator in `wandb.apis.public.artifacts`,
but targets the membership-scoped connection used by `Artifact._resolve_pending_aliases`
instead of the collection-scoped one. Membership aliases are never fetched with
the rest of an artifact -- a membership's `aliases` field is omitted from the
request entirely when pagination is enabled (see `ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION`
call sites), and this paginator fetches the full list, from scratch, the first
time something reads `Artifact.aliases`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from wandb._pydantic import PaginatorVars
from wandb.apis.paginator import RelayPaginator

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.artifacts._generated import ArtifactAliasFragment
    from wandb.sdk.artifacts._models.pagination import ArtifactAliasConnection

DEFAULT_PAGE_SIZE = 1_000


class _MembershipAliasesVars(PaginatorVars):
    entity: str
    project: str
    name: str
    per_page: int = DEFAULT_PAGE_SIZE


class MembershipAliasesPaginator(RelayPaginator["ArtifactAliasFragment", str]):
    """Paginates a membership's aliases, from the start or a previous cursor."""

    QUERY: ClassVar[str | None] = None
    last_response: ArtifactAliasConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        *,
        entity: str,
        project: str,
        name: str,
        per_page: int = DEFAULT_PAGE_SIZE,
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

        # `ArtifactAliasConnection`'s edges require a non-null `node`, unlike
        # the generated type above (which allows one, per the schema) --
        # drop any before re-validating, rather than raising on an
        # otherwise-usable page over one unexpected null.
        connection = membership.aliases_connection
        non_null_edges = [edge for edge in connection.edges if edge.node]
        self.last_response = ArtifactAliasConnection.model_validate(
            connection.model_copy(update={"edges": non_null_edges})
        )

    def _convert(self, node: ArtifactAliasFragment) -> str:
        return node.alias

    def __next__(self) -> str:
        # A page can contain only null nodes while still advertising another
        # page. Keep paging until an alias is available or the connection ends.
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    next = __next__
