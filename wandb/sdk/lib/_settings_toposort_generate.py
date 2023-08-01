import inspect
import sys
from typing import Dict, List, Set, Tuple

from wandb.errors import UsageError
from wandb.sdk.wandb_settings import Settings

if sys.version_info >= (3, 8):
    from typing import get_type_hints
else:
    from typing_extensions import get_type_hints


template = """
__all__ = ("SETTINGS_TOPOLOGICALLY_SORTED", "_Setting")

import sys
from typing import Tuple

if sys.version_info >= (3, 8):
    from typing import Final, Literal
else:
    from typing_extensions import Final, Literal


_Setting = Literal[
    $settings_literal_list
]

SETTINGS_TOPOLOGICALLY_SORTED: Final[Tuple[_Setting, ...]] = (
    $settings_topologically_sorted
)
"""


class Graph:
    # A simple class representing an unweighted directed graph
    # that uses an adjacency list representation.
    # We use to ensure that we don't have cyclic dependencies in the settings
    # and that modifications to the settings are applied in the correct order.
    def __init__(self) -> None:
        self.adj_list: Dict[str, Set[str]] = {}

    def add_node(self, node: str) -> None:
        if node not in self.adj_list:
            self.adj_list[node] = set()

    def add_edge(self, node1: str, node2: str) -> None:
        self.adj_list[node1].add(node2)

    def get_neighbors(self, node: str) -> Set[str]:
        return self.adj_list[node]

    # return a list of nodes sorted in topological order
    def topological_sort_dfs(self) -> List[str]:
        sorted_copy = {k: sorted(v) for k, v in self.adj_list.items()}

        sorted_nodes: List[str] = []
        visited_nodes: Set[str] = set()
        current_nodes: Set[str] = set()

        def visit(n: str) -> None:
            if n in visited_nodes:
                return None
            if n in current_nodes:
                raise UsageError("Cyclic dependency detected in wandb.Settings")

            current_nodes.add(n)
            for neighbor in sorted_copy[n]:
                visit(neighbor)

            current_nodes.remove(n)
            visited_nodes.add(n)
            sorted_nodes.append(n)

            return None

        for node in self.adj_list:
            if node not in visited_nodes:
                visit(node)

        return sorted_nodes


def _get_modification_order(
    settings: Settings,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Return the order in which settings should be modified, based on dependencies."""
    dependency_graph = Graph()

    props = tuple(get_type_hints(Settings).keys())

    # discover prop dependencies from validator methods and runtime hooks

    prefix = "_validate_"
    symbols = set(dir(settings))
    validator_methods = tuple(sorted(m for m in symbols if m.startswith(prefix)))

    # extract dependencies from validator methods
    for m in validator_methods:
        setting = m.split(prefix)[1]
        dependency_graph.add_node(setting)
        # if the method is not static, inspect its code to find the attributes it depends on
        if (
            not isinstance(Settings.__dict__[m], staticmethod)
            and not isinstance(Settings.__dict__[m], classmethod)
            and Settings.__dict__[m].__code__.co_argcount > 0
        ):
            unbound_closure_vars = inspect.getclosurevars(Settings.__dict__[m]).unbound
            dependencies = (v for v in unbound_closure_vars if v in props)
            for d in dependencies:
                dependency_graph.add_node(d)
                dependency_graph.add_edge(setting, d)

    # extract dependencies from props' runtime hooks
    default_props = settings._default_props()
    for prop, spec in default_props.items():
        if "hook" not in spec:
            continue

        dependency_graph.add_node(prop)

        hook = spec["hook"]
        if callable(hook):
            hook = [hook]

        for h in hook:
            unbound_closure_vars = inspect.getclosurevars(h).unbound
            dependencies = (v for v in unbound_closure_vars if v in props)
            for d in dependencies:
                dependency_graph.add_node(d)
                dependency_graph.add_edge(prop, d)

    modification_order = dependency_graph.topological_sort_dfs()
    return props, tuple(modification_order)


def generate(settings: Settings) -> None:
    _settings_literal_list, _settings_topologically_sorted = _get_modification_order(
        settings
    )
    settings_literal_list = ", ".join(f'"{s}"' for s in _settings_literal_list)
    settings_topologically_sorted = ", ".join(
        f'"{s}"' for s in _settings_topologically_sorted
    )

    print(
        template.replace(
            "$settings_literal_list",
            settings_literal_list,
        ).replace(
            "$settings_topologically_sorted",
            settings_topologically_sorted,
        )
    )


if __name__ == "__main__":
    generate(Settings())
