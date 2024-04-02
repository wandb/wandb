import filecmp
import logging
import os

import requests

import wandb

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _compare_artifact_manifests(
    src_art: wandb.Artifact, dst_art: wandb.Artifact
) -> list:
    problems = []
    if isinstance(dst_art, wandb.CommError):
        return ["commError"]

    if src_art.digest != dst_art.digest:
        problems.append(f"digest mismatch {src_art.digest=}, {dst_art.digest=}")

    for name, src_entry in src_art.manifest.entries.items():
        dst_entry = dst_art.manifest.entries.get(name)
        if dst_entry is None:
            problems.append(f"missing manifest entry {name=}, {src_entry=}")
            continue

        for attr in ["path", "digest", "size"]:
            if getattr(src_entry, attr) != getattr(dst_entry, attr):
                problems.append(
                    f"manifest entry mismatch {attr=}, {getattr(src_entry, attr)=}, {getattr(dst_entry, attr)=}"
                )

    return problems


def _compare_artifact_dirs(src_dir, dst_dir) -> list:
    def compare(src_dir, dst_dir):
        comparison = filecmp.dircmp(src_dir, dst_dir)
        differences = {
            "left_only": comparison.left_only,
            "right_only": comparison.right_only,
            "diff_files": comparison.diff_files,
            "subdir_differences": {},
        }

        # Recursively find differences in subdirectories
        for subdir in comparison.subdirs:
            subdir_src = os.path.join(src_dir, subdir)
            subdir_dst = os.path.join(dst_dir, subdir)
            subdir_differences = compare(subdir_src, subdir_dst)
            # If there are differences, add them to the result
            if subdir_differences and any(subdir_differences.values()):
                differences["subdir_differences"][subdir] = subdir_differences

        if all(not diff for diff in differences.values()):
            return None

        return differences

    return compare(src_dir, dst_dir)


def _check_entries_are_downloadable(art):
    entries = _collect_entries(art)
    for entry in entries:
        if not _check_entry_is_downloable(entry):
            return False
    return True


def _collect_entries(art):
    has_next_page = True
    cursor = None
    entries = []
    while has_next_page:
        attrs = art._fetch_file_urls(cursor)
        has_next_page = attrs["pageInfo"]["hasNextPage"]
        cursor = attrs["pageInfo"]["endCursor"]
        for edge in attrs["edges"]:
            name = edge["node"]["name"]
            entry = art.get_entry(name)
            entry._download_url = edge["node"]["directUrl"]
            entries.append(entry)
    return entries


def _check_entry_is_downloable(entry):
    url = entry._download_url
    expected_size = entry.size

    try:
        resp = requests.head(url, allow_redirects=True)
    except Exception as e:
        logger.error(f"Problem validating {entry=}, {e=}")
        return False

    if resp.status_code != 200:
        return False

    actual_size = resp.headers.get("content-length", -1)
    actual_size = int(actual_size)

    if expected_size == actual_size:
        return True

    return False
