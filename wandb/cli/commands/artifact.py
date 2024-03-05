import os

import click
from click import ClickException

import wandb
from wandb import util
from wandb.apis import InternalApi, PublicApi
from wandb.cli.utils.errors import display_error
from wandb.sdk.artifacts.artifact_file_cache import get_artifact_file_cache


@click.group(
    name="artifact",
    help="Commands for interacting with artifacts",
)
def artifact():
    pass


@artifact.command(
    context_settings={"default_map": {}},
    help="Upload an artifact to wandb",
)
@click.argument("path")
@click.option(
    "--name", "-n", help="The name of the artifact to push: project/artifact_name"
)
@click.option("--description", "-d", help="A description of this artifact")
@click.option("--type", "-t", default="dataset", help="The type of the artifact")
@click.option(
    "--alias",
    "-a",
    default=["latest"],
    multiple=True,
    help="An alias to apply to this artifact",
)
@click.option("--id", "run_id", help="The run you want to upload to.")
@click.option(
    "--resume",
    is_flag=True,
    default=None,
    help="Resume the last run from your current directory.",
)
@display_error
def put(path, name, description, type, alias, run_id, resume):
    if name is None:
        name = os.path.basename(path)
    public_api = PublicApi()
    entity, project, artifact_name = public_api._parse_artifact_path(name)
    if project is None:
        project = click.prompt("Enter the name of the project you want to use")
    # TODO: settings nightmare...
    api = InternalApi()
    api.set_setting("entity", entity)
    api.set_setting("project", project)
    artifact = wandb.Artifact(name=artifact_name, type=type, description=description)
    artifact_path = f"{entity}/{project}/{artifact_name}:{alias[0]}"
    if os.path.isdir(path):
        wandb.termlog(f'Uploading directory {path} to: "{artifact_path}" ({type})')
        artifact.add_dir(path)
    elif os.path.isfile(path):
        wandb.termlog(f'Uploading file {path} to: "{artifact_path}" ({type})')
        artifact.add_file(path)
    elif "://" in path:
        wandb.termlog(
            f'Logging reference artifact from {path} to: "{artifact_path}" ({type})'
        )
        artifact.add_reference(path)
    else:
        raise ClickException("Path argument must be a file or directory")

    with wandb.init(
        entity=entity,
        project=project,
        config={"path": path},
        job_type="cli_put",
        id=run_id,
        resume=resume,
    ) as run:
        run.log_artifact(artifact, aliases=alias)
    artifact.wait()

    wandb.termlog(
        "Artifact uploaded, use this artifact in a run by adding:\n", prefix=False
    )
    wandb.termlog(
        f'    artifact = run.use_artifact("{artifact.source_qualified_name}")\n',
        prefix=False,
    )


@artifact.command(
    context_settings={"default_map": {}},
    help="Download an artifact from wandb",
)
@click.argument("path")
@click.option("--root", help="The directory you want to download the artifact to")
@click.option("--type", help="The type of artifact you are downloading")
@display_error
def get(path, root, type):
    public_api = PublicApi()
    entity, project, artifact_name = public_api._parse_artifact_path(path)
    if project is None:
        project = click.prompt("Enter the name of the project you want to use")

    try:
        artifact_parts = artifact_name.split(":")
        if len(artifact_parts) > 1:
            version = artifact_parts[1]
            artifact_name = artifact_parts[0]
        else:
            version = "latest"
        full_path = f"{entity}/{project}/{artifact_name}:{version}"
        wandb.termlog(
            "Downloading {type} artifact {full_path}".format(
                type=type or "dataset", full_path=full_path
            )
        )
        artifact = public_api.artifact(full_path, type=type)
        path = artifact.download(root=root)
        wandb.termlog("Artifact downloaded to %s" % path)
    except ValueError:
        raise ClickException("Unable to download artifact")


@artifact.command(
    context_settings={"default_map": {}},
    help="List all artifacts in a wandb project",
)
@click.argument("path")
@click.option("--type", "-t", help="The type of artifacts to list")
@display_error
def ls(path, type):
    public_api = PublicApi()
    if type is not None:
        types = [public_api.artifact_type(type, path)]
    else:
        types = public_api.artifact_types(path)

    for kind in types:
        for collection in kind.collections():
            versions = public_api.artifact_versions(
                kind.type,
                "/".join([kind.entity, kind.project, collection.name]),
                per_page=1,
            )
            latest = next(versions)
            print(
                "{:<15s}{:<15s}{:>15s} {:<20s}".format(
                    kind.type,
                    latest.updated_at,
                    util.to_human_size(latest.size),
                    latest.name,
                )
            )


@artifact.group(help="Commands for interacting with the artifact cache")
def cache():
    pass


@cache.command(
    context_settings={"default_map": {}},
    help="Clean up less frequently used files from the artifacts cache",
)
@click.argument("target_size")
@click.option("--remove-temp/--no-remove-temp", default=False, help="Remove temp files")
@display_error
def cleanup(target_size, remove_temp):
    target_size = util.from_human_size(target_size)
    cache = get_artifact_file_cache()
    reclaimed_bytes = cache.cleanup(target_size, remove_temp)
    print(f"Reclaimed {util.to_human_size(reclaimed_bytes)} of space")
