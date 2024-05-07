"""Benchmark large artifacts.

The simplest way of running this benchmark is just
`python large_artifact_benchmark.py`

That runs all the individual benchmarks in order. Most likely, the main options you'll
want to change are `--count` and `--size`, which default to fairly small values.

To run only some of the benchmarks, or to manually decide how to chain them, you can use
the subcommands:
```sh
python large_artifact_benchmark.py upload download incremental --modify 10 download
```
Would create a new artifact, download the original, incrementally modify 10 files, and
then download that new artifact.

```sh
python large_artifact_benchmark.py download --qualified_name="me/foo/bar:v3"
```
Downloads a pre-existing artifact `me/foo/bar:v3`.


Options:
  --count INTEGER       number of artifact files
  --size INTEGER        size of each file
  --name TEXT           artifact name
  --cache / --no-cache  use the artifact cache
  --stage / --no-stage  copy files to staging area
  --project TEXT
  --entity TEXT
  --help                Show this message and exit.

Commands and additional options:
  download              Benchmark downloading a large artifact.
    --qualified-name      fully qualified artifact name
  incremental           Benchmark incremental changes to a large artifact.
    --add                 number of files to add
    --remove              number of files to remove
    --modify              number of files to modify
    --qualified-name      fully qualified artifact name
  upload                Upload a large artifact.
"""

import contextlib
import os
import sys
from datetime import timedelta
from pathlib import Path
from secrets import token_hex, token_urlsafe
from subprocess import CalledProcessError, check_output
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Optional

import click
import wandb


def duration(end: float, start: float = 0) -> str:
    """Turn a duration in seconds into a human-readable string."""
    seconds = end - start
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return str(timedelta(seconds=int(end - start)))


@click.group(invoke_without_command=True, chain=True)
@click.pass_context
@click.option("--count", default=1000, help="number of artifact files")
@click.option("--size", default=8, help="size of each file")
@click.option("--name", default="{git_sha}-{count}x{size}", help="artifact name")
@click.option("--cache/--no-cache", default=False, help="use the artifact cache")
@click.option("--stage/--no-stage", default=False, help="copy files to staging area")
@click.option("--project", default="artifact-benchmark")
@click.option("--entity", default="wandb-artifacts-dev")
@click.option("--core/--no-core", default=True, help="use the Go core")
def cli(
    ctx: click.Context,
    *,
    count: int,
    size: int,
    name: str,
    cache: bool,
    stage: bool,
    project: str,
    entity: str,
    core: bool,
) -> None:
    ctx.ensure_object(dict)

    version = wandb.__version__
    git_sha = None
    with contextlib.suppress(CalledProcessError):
        git_sha = check_output(["git", "rev-parse", "HEAD"]).decode("utf-8")[:8]
    print(f"python version: {sys.version}")
    print(f"wandb version: {version}{f'@{git_sha}' if git_sha else ''}")

    if core:
        wandb.require("core")

    ctx.obj["count"] = count
    ctx.obj["size"] = size
    ctx.obj["entity"] = entity

    params = {
        "count": count,
        "size": size,
        "entity": entity,
        "project": project,
        "name": name,
        "cache": cache,
        "stage": stage,
        "version": version,
        "git_sha": git_sha or "unknown",
        "random": token_urlsafe(8),
    }

    ctx.obj["project"] = project.format(**params)
    ctx.obj["name"] = name.format(**params)
    qualified_name = f"{entity}/{ctx.obj['project']}/{ctx.obj['name']}"
    if ":" not in qualified_name:
        qualified_name += ":latest"
    ctx.obj["qualified_name"] = qualified_name
    ctx.obj["skip_cache"] = not cache
    ctx.obj["policy"] = "mutable" if stage else "immutable"

    os.environ["WANDB_SILENT"] = "true"

    wandb.login()  # Ensure our credentials work before doing anything time consuming.

    if ctx.invoked_subcommand is None:
        start = perf_counter()
        ctx.invoke(upload)
        ctx.invoke(incremental, add=1)
        ctx.invoke(incremental, remove=1)
        ctx.invoke(incremental, modify=1)
        ctx.invoke(download)
        done = perf_counter()
        print("=================================")
        print(f"Entire benchmark: {duration(done, start)}")


@cli.command("upload")
@click.pass_context
def upload(ctx) -> None:
    """Upload a large artifact."""
    o = ctx.obj
    print(f"Uploading {o['count']} {o['size']}-byte files as {o['qualified_name']}")
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for i in range(o["count"]):
            path = root / f"{i % 1000:03}" / f"{i // 1000:06}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token_hex((o["size"] + 1) // 2)[: o["size"]])
        print(f"\tcreated {o['count']} test files under {root}")

        start = perf_counter()
        with wandb.init(
            project=o["project"],
            entity=o["entity"],
            settings={"console": "off"},
            config={"file_count": o["count"], "file_size": o["size"]},
        ) as run:
            begin = perf_counter()
            artifact = wandb.Artifact(name=o["name"], type="test")
            artifact.add_dir(root, skip_cache=o["skip_cache"], policy=o["policy"])
            add_done = perf_counter()
            print(f"\tadd files: {duration(add_done, begin)}")
            run.log_artifact(artifact)
            artifact.wait()
            o["qualified_name"] = artifact.qualified_name
            end = perf_counter()
            print(f"\tupload files: {duration(end, add_done)}")
            mb_per_s = (o["count"] * o["size"] / 1000000) / (end - begin)
            ms_per_file = duration((end - begin) / o["count"])
            print(
                f"\ttotal: {duration(end, begin)} "
                f"({ms_per_file}/file, {mb_per_s:.3f}MB/s)"
            )
        stop = perf_counter()
        print(f"\tincluding startup/teardown: {duration(stop, start)}")


@cli.command("incremental")
@click.pass_context
@click.option("--add", default=0, help="number of files to add")
@click.option("--remove", default=0, help="number of files to remove")
@click.option("--modify", default=0, help="number of files to modify")
@click.option("--qualified-name", help="fully qualified artifact name")
def incremental(
    ctx: click.Context,
    add: int,
    remove: int,
    modify: int,
    qualified_name: Optional[str],
) -> None:
    """Benchmark incremental changes to a large artifact."""
    if not qualified_name:
        qualified_name = ctx.obj["qualified_name"]
    o = ctx.obj
    start = perf_counter()
    with TemporaryDirectory() as tmpdir, wandb.init(
        project=o["project"], entity=o["entity"], settings={"console": "off"}
    ) as run:
        root = Path(tmpdir)
        operations = []
        if add > 0:
            operations.append(f"add {add}")
        if remove > 0:
            operations.append(f"remove {remove}")
        if modify > 0:
            operations.append(f"modify {modify}")
        print(f"Incremental: {', '.join(operations)} from {o['qualified_name']}")

        begin = perf_counter()
        artifact = wandb.Api().artifact(o["qualified_name"]).new_draft()
        done_create_draft = perf_counter()
        print(f"\tcreate draft: {duration(done_create_draft, begin)}")

        if add > 0:
            start_add = perf_counter()
            for _ in range(add):
                path = root / f"{token_urlsafe(8)}.txt"
                path.write_text(token_hex((o["size"] + 1) // 2)[: o["size"]])
            artifact.add_dir(root, skip_cache=o["skip_cache"], policy=o["policy"])
            done_add = perf_counter()
            print(f"\tadd files: {duration(done_add, start_add)}")

        if remove > 0:
            start_remove = perf_counter()
            for entry in list(artifact.manifest.entries.values())[:remove]:
                artifact.remove(entry)
            done_remove = perf_counter()
            print(f"\tremove files: {duration(done_remove, start_remove)}")

        if modify > 0:
            start_modify = perf_counter()
            for entry in list(artifact.manifest.entries.values())[:modify]:
                artifact.remove(entry)
                path = root / Path(entry.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(token_hex((o["size"] + 1) // 2)[: o["size"]])
                artifact.add_file(path, skip_cache=o["skip_cache"], policy=o["policy"])
            done_modify = perf_counter()
            print(f"\tmodify files: {duration(done_modify, start_modify)}")

        start_log = perf_counter()
        run.log_artifact(artifact)
        artifact.wait()
        o["qualified_name"] = artifact.qualified_name
        done_log = perf_counter()
        print(f"\tlog artifact: {duration(done_log, start_log)}")
        print(f"\ttotal: {duration(done_log, begin)}")
    stop = perf_counter()
    print(f"\tincluding startup/teardown: {duration(stop, start)}")


@cli.command("download")
@click.pass_context
@click.option("--qualified-name", help="fully qualified artifact name")
def download(ctx: click.Context, qualified_name: Optional[str]) -> None:
    """Benchmark downloading a large artifact."""
    if not qualified_name:
        qualified_name = ctx.obj["qualified_name"]
    print(f"Downloading {qualified_name}")
    with TemporaryDirectory() as tmpdir:
        begin = perf_counter()
        artifact = wandb.Api().artifact(qualified_name)
        _ = artifact.manifest
        done_retrieve_manifest = perf_counter()
        print("\tretrieve manifest: ", duration(done_retrieve_manifest, begin))
        artifact.download(root=tmpdir, skip_cache=ctx.obj["skip_cache"])
        end = perf_counter()
        print(f"\tdownload files: {duration(end, done_retrieve_manifest)}")
        size_mb = sum(e.size for e in artifact.manifest.entries.values()) / 1000000
        mb_per_s = size_mb / (end - begin)
        ms_per_file = duration((end - begin) / len(artifact.manifest.entries))
        print(
            f"\ttotal: {duration(end, begin)} "
            f"({ms_per_file}/file, {mb_per_s:.3f}MB/s)"
        )


if __name__ == "__main__":
    cli(obj={})
