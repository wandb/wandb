from typing import Any, Dict, List


class ConfigPath:
    """Thin list wrapper representing a key-path within nested dictionarys."""

    def __init__(self, path: str):
        self.path = split_on_unesc_dot(path)

    def __getitem__(self, index):
        return self.path[index]

    def __setitem__(self, index, value):
        self.path[index] = value

    def __delitem__(self, index):
        del self.path[index]

    def __len__(self):
        return len(self.path)

    def __iter__(self):
        return iter(self.path)

    def __contains__(self, item):
        return item in self.path


def filter_tree(
    tree: Dict[str, Any],
    include: List[ConfigPath],
    exclude: List[ConfigPath],
):
    """Filter a tree of nested dictionaries.

    Args:
        tree (Dict[str, Any]): The tree to filter.
        include (List[ConfigPath]): A list of keys to include in the tree.
        exclude (List[ConfigPath]): A list of keys to exclude from the tree.

    Returns:
        Dict[str, Any]: The filtered tree.
    """
    if not include and not exclude:
        return tree
    filtered_tree = {}
    for path, subtree in include_tree(tree, include):
        if not exclude_tree(subtree, exclude):
            set_tree(filtered_tree, path, subtree)
    return filtered_tree


def include_tree(
    tree: Dict[str, Any],
    include: List[ConfigPath],
) -> List[Dict[str, Any]]:
    """Include a list of subtrees from a tree.

    Args:
        tree (Dict[str, Any]): The tree to include subtrees from.
        include (List[ConfigPath]): A list of keys to include in the tree.

    Returns:
        List[Dict[str, Any]]: A list of subtrees.
    """
    subtrees = []
    for path in include:
        subtree = get_tree(tree, path)
        if subtree is not None:
            subtrees.append((path, subtree))
    return subtrees


def exclude_tree(
    tree: Dict[str, Any],
    exclude: List[ConfigPath],
) -> bool:
    """Exclude a list of subtrees from a tree.

    Args:
        tree (Dict[str, Any]): The tree to exclude subtrees from.
        exclude (List[ConfigPath]): A list of keys to exclude from the tree.

    Returns:
        bool: True if the tree is excluded, False otherwise.
    """
    for path in exclude:
        if get_tree(tree, path) is not None:
            return True
    return False


def get_tree(tree: Dict[str, Any], path: ConfigPath) -> Any:
    """Get a subtree from a tree.

    Args:
        tree (Dict[str, Any]): The tree to get the subtree from.
        path (ConfigPath): The path to the subtree.

    Returns:
        Any: The subtree.
    """
    subtree = tree
    for part in path:
        if part not in subtree:
            return None
        subtree = subtree[part]
    return subtree


def set_tree(tree: Dict[str, Any], path: ConfigPath, subtree: Any):
    """Set a subtree in a tree.

    Args:
        tree (Dict[str, Any]): The tree to set the subtree in.
        path (ConfigPath): The path to the subtree.
        subtree (Any): The subtree to set.
    """
    for part in path[:-1]:
        if part not in tree:
            tree[part] = {}
        tree = tree[part]
    tree[path[-1]] = subtree


def parse_subtree_paths(paths: List[str]) -> List[ConfigPath]:
    """Parse a list of dot separated paths into a dictionary of subtrees.

    Args:
        paths (List[str]): A list of dot separated paths.

    Returns:
        Dict[str, Set[str]]: A dictionary of subtrees with the keys being the
            paths to the subtrees and the values being the set of keys in the
            subtree.
    """
    subtree_paths = {}
    for path in paths:
        parts = path.split(".")
        subtree = subtree_paths
        for part in parts:
            if part not in subtree:
                subtree[part] = {}
            subtree = subtree[part]
    return subtree_paths


def split_on_unesc_dot(path: str) -> List[str]:
    r"""Split a string on unescaped dots.

    Args:
        path (str): The string to split.

    Returns:
        List[str]: The split string.
    """
    parts = []
    part = ""
    i = 0
    while i < len(path):
        if path[i] == "\\":
            part += path[i + 1]
            i += 1
        elif path[i] == ".":
            parts.append(part)
            part = ""
        else:
            part += path[i]
        i += 1
    parts.append(part)
    return parts
