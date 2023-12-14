#
from typing import Any, Dict, Iterable


def split_files(
    files: Dict[str, Any], max_bytes: int = 10 * 1024 * 1024
) -> Iterable[Dict[str, Dict]]:
    """Split a file's dict (see `files` arg) into smaller dicts.

    Each smaller dict will have at most `MAX_BYTES` size.

    This method is used in `FileStreamAPI._send()` to limit the size of post requests
    sent to wandb server.

    Arguments:
    files (dict): `dict` of form {file_name: {'content': ".....", 'offset': 0}}
        The key `file_name` can also be mapped to a List [{"offset": int, "content": str}]
    `max_bytes`: max size for chunk in bytes
    """
    current_volume: Dict[str, Dict] = {}
    current_size = 0

    def _str_size(x):
        return len(x) if isinstance(x, bytes) else len(x.encode("utf-8"))

    def _file_size(file):
        size = file.get("_size")
        if size is None:
            size = sum(map(_str_size, file["content"]))
            file["_size"] = size
        return size

    def _split_file(file, num_lines):
        offset = file["offset"]
        content = file["content"]
        name = file["name"]
        f1 = {"offset": offset, "content": content[:num_lines], "name": name}
        f2 = {
            "offset": offset + num_lines,
            "content": content[num_lines:],
            "name": name,
        }
        return f1, f2

    def _num_lines_from_num_bytes(file, num_bytes):
        size = 0
        num_lines = 0
        content = file["content"]
        while num_lines < len(content):
            size += _str_size(content[num_lines])
            if size > num_bytes:
                break
            num_lines += 1
        return num_lines

    files_stack = []
    for k, v in files.items():
        if isinstance(v, list):
            for item in v:
                files_stack.append(
                    {"name": k, "offset": item["offset"], "content": item["content"]}
                )
        else:
            files_stack.append(
                {"name": k, "offset": v["offset"], "content": v["content"]}
            )

    while files_stack:
        f = files_stack.pop()
        if f["name"] in current_volume:
            files_stack.append(f)
            yield current_volume
            current_volume = {}
            current_size = 0
            continue
        # For each file, we have to do 1 of 4 things:
        # - Add the file as such to the current volume if possible.
        # - Split the file and add the first part to the current volume and push the second part back onto the stack.
        # - If that's not possible, check if current volume is empty:
        # - If empty, add first line of file to current volume and push rest onto stack (This volume will exceed MAX_MB).
        # - If not, push file back to stack and yield current volume.
        fsize = _file_size(f)
        rem = max_bytes - current_size
        if fsize <= rem:
            current_volume[f["name"]] = {
                "offset": f["offset"],
                "content": f["content"],
            }
            current_size += fsize
        else:
            num_lines = _num_lines_from_num_bytes(f, rem)
            if not num_lines and not current_volume:
                num_lines = 1
            if num_lines:
                f1, f2 = _split_file(f, num_lines)
                current_volume[f1["name"]] = {
                    "offset": f1["offset"],
                    "content": f1["content"],
                }
                files_stack.append(f2)
                yield current_volume
                current_volume = {}
                current_size = 0
                continue
            else:
                files_stack.append(f)
                yield current_volume
                current_volume = {}
                current_size = 0
                continue
        if current_size >= max_bytes:
            yield current_volume
            current_volume = {}
            current_size = 0
            continue

    if current_volume:
        yield current_volume
