from typing import Any, Dict, Optional, TypeVar

from ...public import Api as PublicApi
from ...public import PythonMongoishQueryGenerator, QueryGenerator, Runs
from .util import Attr, Base, coalesce, generate_name, nested_get, nested_set

T = TypeVar("T")


class Runset(Base):
    entity: Optional[str] = Attr(json_path="spec.project.entityName")
    project: Optional[str] = Attr(json_path="spec.project.name")
    name: str = Attr(json_path="spec.name")
    query: str = Attr(json_path="spec.search.query")
    filters: dict = Attr(json_path="spec.filters")
    groupby: list = Attr(json_path="spec.grouping")
    order: list = Attr(json_path="spec.sort")

    def __init__(
        self,
        entity=None,
        project=None,
        name="Run set",
        query="",
        filters=None,
        groupby=None,
        order=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._spec = self._default_runset_spec()
        self.query_generator = QueryGenerator()
        self.pm_query_generator = PythonMongoishQueryGenerator(self)

        self.entity = coalesce(entity, PublicApi().default_entity, "")
        self.project = project  # If the project is None, it will be updated to the report's project on save.  See: Report.save
        self.name = name
        self.query = query
        self.filters = coalesce(filters, self._default_filters())
        self.groupby = coalesce(groupby, self._default_groupby())
        self.order = coalesce(order, self._default_order())

    @classmethod
    def from_json(cls, spec: Dict[str, Any]) -> T:
        """This has a custom implementation because sometimes runsets are missing the project field."""
        obj = cls()
        obj._spec = spec

        project = spec.get("project")
        if project:
            obj.entity = project.get(
                "entityName", coalesce(PublicApi().default_entity, "")
            )
            obj.project = project.get("name")
        else:
            obj.entity = coalesce(PublicApi().default_entity, "")
            obj.project = None

        return obj

    @filters.getter
    def filters(self):
        json_path = self._get_path("filters")
        filter_specs = nested_get(self, json_path)
        return self.query_generator.filter_to_mongo(filter_specs)

    @filters.setter
    def filters(self, new_filters):
        json_path = self._get_path("filters")
        new_filter_specs = self.query_generator.mongo_to_filter(new_filters)
        nested_set(self, json_path, new_filter_specs)

    def set_filters_with_python_expr(self, expr):
        self.filters = self.pm_query_generator.python_to_mongo(expr)
        return self

    @groupby.getter
    def groupby(self):
        json_path = self._get_path("groupby")
        groupby_specs = nested_get(self, json_path)
        cols = [self.query_generator.key_to_server_path(k) for k in groupby_specs]
        return [self.pm_query_generator.back_to_front(c) for c in cols]

    @groupby.setter
    def groupby(self, new_groupby):
        json_path = self._get_path("groupby")
        cols = [self.pm_query_generator.front_to_back(g) for g in new_groupby]
        new_groupby_specs = [self.query_generator.server_path_to_key(c) for c in cols]
        nested_set(self, json_path, new_groupby_specs)

    @order.getter
    def order(self):
        json_path = self._get_path("order")
        order_specs = nested_get(self, json_path)
        cols = self.query_generator.keys_to_order(order_specs)
        return [c[0] + self.pm_query_generator.back_to_front(c[1:]) for c in cols]

    @order.setter
    def order(self, new_orders):
        json_path = self._get_path("order")
        cols = [o[0] + self.pm_query_generator.front_to_back(o[1:]) for o in new_orders]
        new_order_specs = self.query_generator.order_to_keys(cols)
        nested_set(self, json_path, new_order_specs)

    @property
    def _runs_config(self) -> dict:
        return {k: v for run in self.runs for k, v in run.config.items()}

    @property
    def runs(self) -> Runs:
        return PublicApi().runs(
            path=f"{self.entity}/{self.project}", filters=self.filters
        )

    @staticmethod
    def _default_filters():
        return {"$or": [{"$and": []}]}

    @staticmethod
    def _default_groupby():
        return []

    @staticmethod
    def _default_order():
        return ["-CreatedTimestamp"]

    @staticmethod
    def _default_runset_spec():
        return {
            "id": generate_name(),
            "runFeed": {
                "version": 2,
                "columnVisible": {"run:name": False},
                "columnPinned": {},
                "columnWidths": {},
                "columnOrder": [],
                "pageSize": 10,
                "onlyShowSelected": False,
            },
            "enabled": True,
            "selections": {"root": 1, "bounds": [], "tree": []},
            "expandedRowAddresses": [],
        }
