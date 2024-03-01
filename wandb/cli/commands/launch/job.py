import os

import click

import wandb
from wandb import env, util
from wandb.apis import PublicApi
from wandb.cli.utils.api import _get_cling_api


@click.group(
    name="job",
    help="Commands for managing and viewing W&B jobs",
)
def job() -> None:
    pass


@job.command("list", help="List jobs in a project")
@click.option(
    "--project",
    "-p",
    envvar=env.PROJECT,
    help="The project you want to list jobs from.",
)
@click.option(
    "--entity",
    "-e",
    default="models",
    envvar=env.ENTITY,
    help="The entity the jobs belong to",
)
def _list(project, entity):
    wandb.termlog(f"Listing jobs in {entity}/{project}")
    public_api = PublicApi()
    try:
        jobs = public_api.list_jobs(entity=entity, project=project)
    except wandb.errors.CommError as e:
        wandb.termerror(f"{e}")
        return

    if len(jobs) == 0:
        wandb.termlog("No jobs found")
        return

    for job in jobs:
        aliases = []
        if len(job["edges"]) == 0:
            # deleted?
            continue

        name = job["edges"][0]["node"]["artifactSequence"]["name"]
        for version in job["edges"]:
            aliases += [x["alias"] for x in version["node"]["aliases"]]

        # only list the most recent 10 job versions
        aliases_str = ",".join(aliases[::-1])
        wandb.termlog(f"{name} -- versions ({len(aliases)}): {aliases_str}")


@job.command(
    help="Describe a launch job. Provide the launch job in the form of: entity/project/job-name:alias-or-version"
)
@click.argument("job")
def describe(job):
    public_api = PublicApi()
    try:
        job = public_api.job(name=job)
    except wandb.errors.CommError as e:
        wandb.termerror(f"{e}")
        return

    for key in job._job_info:
        if key.startswith("_"):
            continue
        wandb.termlog(f"{key}: {job._job_info[key]}")


@job.command(
    no_args_is_help=True,
)
@click.option(
    "--project",
    "-p",
    envvar=env.PROJECT,
    help="The project you want to list jobs from.",
)
@click.option(
    "--entity",
    "-e",
    envvar=env.ENTITY,
    help="The entity the jobs belong to",
)
@click.option(
    "--name",
    "-n",
    help="Name for the job",
)
@click.option(
    "--description",
    "-d",
    help="Description for the job",
)
@click.option(
    "--alias",
    "-a",
    "aliases",
    help="Alias for the job",
    multiple=True,
    default=tuple(),
)
@click.option(
    "--entry-point",
    "-E",
    "entrypoint",
    help="Codepath to the main script, required for repo jobs",
)
@click.option(
    "--git-hash",
    "-g",
    "git_hash",
    type=str,
    help="Hash to a specific git commit.",
)
@click.option(
    "--runtime",
    "-r",
    type=str,
    help="Python runtime to execute the job",
)
@click.argument(
    "job_type",
    type=click.Choice(("git", "code", "image")),
)
@click.argument("path")
def create(
    path,
    project,
    entity,
    name,
    job_type,
    description,
    aliases,
    entrypoint,
    git_hash,
    runtime,
):
    """Create a job from a source, without a wandb run.

    Jobs can be of three types, git, code, or image.

    git: A git source, with an entrypoint either in the path or provided explicitly pointing to the main python executable.
    code: A code path, containing a requirements.txt file.
    image: A docker image.
    """
    from wandb.sdk.launch.create_job import _create_job

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="job_create")

    entity = entity or os.getenv("WANDB_ENTITY") or api.default_entity
    if not entity:
        wandb.termerror("No entity provided, use --entity or set WANDB_ENTITY")
        return

    project = project or os.getenv("WANDB_PROJECT")
    if not project:
        wandb.termerror("No project provided, use --project or set WANDB_PROJECT")
        return

    if entrypoint is None and job_type in ["git", "code"]:
        wandb.termwarn(
            f"No entrypoint provided for {job_type} job, defaulting to main.py"
        )
        entrypoint = "main.py"

    artifact, action, aliases = _create_job(
        api=api,
        path=path,
        entity=entity,
        project=project,
        name=name,
        job_type=job_type,
        description=description,
        aliases=list(aliases),
        entrypoint=entrypoint,
        git_hash=git_hash,
        runtime=runtime,
    )
    if not artifact:
        wandb.termerror("Job creation failed")
        return

    artifact_path = f"{entity}/{project}/{artifact.name}"
    msg = f"{action} job: {click.style(artifact_path, fg='yellow')}"
    if len(aliases) == 1:
        alias_str = click.style(aliases[0], fg="yellow")
        msg += f", with alias: {alias_str}"
    elif len(aliases) > 1:
        alias_str = click.style(", ".join(aliases), fg="yellow")
        msg += f", with aliases: {alias_str}"

    wandb.termlog(msg)
    web_url = util.app_url(api.settings().get("base_url"))
    url = click.style(f"{web_url}/{entity}/{project}/jobs", underline=True)
    wandb.termlog(f"View all jobs in project '{project}' here: {url}\n")
