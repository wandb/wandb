from __future__ import annotations


class InvalidRepositoryError(Exception):
    """The given string is not a valid repository name."""


def resolve_repository_name(repo_name: str) -> tuple[str, str]:
    if "://" in repo_name:
        raise InvalidRepositoryError(
            f"Repository name cannot contain a scheme ({repo_name})"
        )

    index_name, remote_name = split_repo_name(repo_name)
    if index_name[0] == "-" or index_name[-1] == "-":
        raise InvalidRepositoryError(
            f"Invalid index name ({index_name}). Cannot begin or end with a hyphen."
        )
    return resolve_index_name(index_name), remote_name


def resolve_index_name(index_name: str) -> str:
    index_name = convert_to_hostname(index_name)
    if index_name == "index.docker.io":
        index_name = "docker.io"
    return index_name


def split_repo_name(repo_name: str) -> tuple[str, str]:
    parts = repo_name.split("/", 1)
    if len(parts) == 1 or (
        "." not in parts[0] and ":" not in parts[0] and parts[0] != "localhost"
    ):
        # This is a docker index repo (ex: username/foobar or ubuntu)
        return "docker.io", repo_name
    return parts[0], parts[1]


def convert_to_hostname(url: str) -> str:
    return url.replace("http://", "").replace("https://", "").split("/", 1)[0]
