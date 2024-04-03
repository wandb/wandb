import os
import sys
from datetime import timedelta
from pathlib import Path
from secrets import token_hex, token_urlsafe
from subprocess import CalledProcessError, check_output
from tempfile import TemporaryDirectory
from time import perf_counter

import click
import wandb


def duration(end, start=0):
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
@click.option("--entity", default="wandb")
def cli(
    ctx,
    count: int,
    size: int,
    name: str,
    cache: bool,
    stage: bool,
    project: str,
    entity: str,
) -> None:
    ctx.ensure_object(dict)

    version = wandb.__version__
    git_sha = None
    try:
        git_sha = check_output(["git", "rev-parse", "HEAD"]).decode("utf-8")[:8]
    except CalledProcessError:
        pass
    print(f"python version: {sys.version}")
    print(f"wandb version: {version}{f'@{git_sha}' if git_sha else ''}")

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
    ctx.obj["qualified_name"] = f"{entity}/{project}/{name}:latest"
    ctx.obj["skip_cache"] = not cache
    ctx.obj["policy"] = "mutable" if stage else "immutable"

    os.environ["WANDB_SILENT"] = "true"

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
    o = ctx.obj
    print(f"Uploading {o['count']} {o['size']}-byte files")
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for i in range(o["count"]):
            path = root / f"{i % 1000:03}" / f"{i // 1000:06}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token_hex((o["size"] + 1) // 2)[: o["size"]])

        start = perf_counter()
        with wandb.init(
            project=o["project"], entity=o["entity"], settings={"console": "off"}
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
def incremental(ctx, add: int, remove: int, modify: int) -> None:
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
            for i in range(len(artifact.manifest), len(artifact.manifest) + add):
                path = root / f"{i % 1000:03}" / f"{i // 1000:06}.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
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
@click.option("--name", help="fully qualified artifact name")
def download(ctx, name: str | None) -> None:
    if name is None:
        name = ctx.obj["qualified_name"]
    else:
        ctx.obj["qualified_name"] = name
    print(f"Downloading {name}")
    with TemporaryDirectory() as tmpdir:
        begin = perf_counter()
        artifact = wandb.Api().artifact(name)
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
