import os
import subprocess

import click
import yaml
from click import ClickException

import wandb
from wandb import Config, env, util
from wandb.cli.commands.docker import docker
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import display_error
from wandb.sdk.lib import filesystem


@click.command(
    name="restore",
    context_settings={"default_map": {}},
    help="Restore code, config and docker state for a run",
)
@click.pass_context
@click.argument("run", envvar=env.RUN_ID)
@click.option("--no-git", is_flag=True, default=False, help="Don't restore git state")
@click.option(
    "--branch/--no-branch",
    default=True,
    help="Whether to create a branch or checkout detached",
)
@click.option(
    "--project", "-p", envvar=env.PROJECT, help="The project you wish to upload to."
)
@click.option(
    "--entity", "-e", envvar=env.ENTITY, help="The entity to scope the listing to."
)
@display_error
def restore(ctx, run, no_git, branch, project, entity):  # noqa: C901
    from wandb.old.core import wandb_dir

    api = _get_cling_api()
    if ":" in run:
        if "/" in run:
            entity, rest = run.split("/", 1)
        else:
            rest = run
        project, run = rest.split(":", 1)
    elif run.count("/") > 1:
        entity, run = run.split("/", 1)

    project, run = api.parse_slug(run, project=project)
    commit, json_config, patch_content, metadata = api.run_config(
        project, run=run, entity=entity
    )
    repo = metadata.get("git", {}).get("repo")
    image = metadata.get("docker")
    restore_message = (
        """`wandb restore` needs to be run from the same git repository as the original run.
Run `git clone %s` and restore from there or pass the --no-git flag."""
        % repo
    )
    if no_git:
        commit = None
    elif not api.git.enabled:
        if repo:
            raise ClickException(restore_message)
        elif image:
            wandb.termlog(
                "Original run has no git history.  Just restoring config and docker"
            )

    if commit and api.git.enabled:
        wandb.termlog(f"Fetching origin and finding commit: {commit}")
        subprocess.check_call(["git", "fetch", "--all"])
        try:
            api.git.repo.commit(commit)
        except ValueError:
            wandb.termlog(f"Couldn't find original commit: {commit}")
            commit = None
            files = api.download_urls(project, run=run, entity=entity)
            for filename in files:
                if filename.startswith("upstream_diff_") and filename.endswith(
                    ".patch"
                ):
                    commit = filename[len("upstream_diff_") : -len(".patch")]
                    try:
                        api.git.repo.commit(commit)
                    except ValueError:
                        commit = None
                    else:
                        break

            if commit:
                wandb.termlog(f"Falling back to upstream commit: {commit}")
                patch_path, _ = api.download_write_file(files[filename])
            else:
                raise ClickException(restore_message)
        else:
            if patch_content:
                patch_path = os.path.join(wandb_dir(), "diff.patch")
                with open(patch_path, "w") as f:
                    f.write(patch_content)
            else:
                patch_path = None

        branch_name = "wandb/%s" % run
        if branch and branch_name not in api.git.repo.branches:
            api.git.repo.git.checkout(commit, b=branch_name)
            wandb.termlog("Created branch %s" % click.style(branch_name, bold=True))
        elif branch:
            wandb.termlog(
                "Using existing branch, run `git branch -D %s` from master for a clean checkout"
                % branch_name
            )
            api.git.repo.git.checkout(branch_name)
        else:
            wandb.termlog("Checking out %s in detached mode" % commit)
            api.git.repo.git.checkout(commit)

        if patch_path:
            # we apply the patch from the repository root so git doesn't exclude
            # things outside the current directory
            root = api.git.root
            patch_rel_path = os.path.relpath(patch_path, start=root)
            # --reject is necessary or else this fails any time a binary file
            # occurs in the diff
            exit_code = subprocess.call(
                ["git", "apply", "--reject", patch_rel_path], cwd=root
            )
            if exit_code == 0:
                wandb.termlog("Applied patch")
            else:
                wandb.termerror(
                    "Failed to apply patch, try un-staging any un-committed changes"
                )

    filesystem.mkdir_exists_ok(wandb_dir())
    config_path = os.path.join(wandb_dir(), "config.yaml")
    config = Config()
    for k, v in json_config.items():
        if k not in ("_wandb", "wandb_version"):
            config[k] = v
    s = b"wandb_version: 1"
    s += b"\n\n" + yaml.dump(
        config._as_dict(),
        Dumper=yaml.SafeDumper,
        default_flow_style=False,
        allow_unicode=True,
        encoding="utf-8",
    )
    s = s.decode("utf-8")
    with open(config_path, "w") as f:
        f.write(s)

    wandb.termlog("Restored config variables to %s" % config_path)
    if image:
        if not metadata["program"].startswith("<") and metadata.get("args") is not None:
            # TODO: we may not want to default to python here.
            runner = util.find_runner(metadata["program"]) or ["python"]
            command = runner + [metadata["program"]] + metadata["args"]
            cmd = " ".join(command)
        else:
            wandb.termlog("Couldn't find original command, just restoring environment")
            cmd = None
        wandb.termlog("Docker image found, attempting to start")
        ctx.invoke(docker, docker_run_args=[image], cmd=cmd)

    return commit, json_config, patch_content, repo, metadata
