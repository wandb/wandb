# Information about the system and the environment
import datetime
import glob
import json
import logging
import os
import subprocess
import sys
from shutil import copyfile
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.lib import filesystem
from wandb.sdk.lib.filenames import CONDA_ENVIRONMENTS_FNAME, DIFF_FNAME, METADATA_FNAME
from wandb.sdk.lib.gitlib import GitRepo

from .assets.interfaces import Interface

logger = logging.getLogger(__name__)


class SystemInfo:
    # todo: this is mostly a copy of the legacy Meta class, but it should be refactored
    def __init__(self, settings: SettingsStatic, interface: Interface) -> None:
        logger.debug("System info init")
        self.settings = settings

        self.metadata_file_name = os.path.join(self.settings.files_dir, METADATA_FNAME)
        self.backend_interface = interface
        self.git = GitRepo(
            root=self.settings.git_root,
            remote=self.settings.git_remote,
            remote_url=self.settings.git_remote_url,
            commit=self.settings.git_commit,
        )
        # Location under "code" directory in files where program was saved.
        self.saved_program: Optional[os.PathLike] = None
        # Locations under files directory where diff patches were saved.
        self.saved_patches: List[str] = []
        logger.debug("System info init done")

    def _save_code(self) -> None:
        logger.debug("Saving code")
        if not self.settings.program_relpath:
            logger.warning("unable to save code -- program entry not found")
            return None

        root: str = self.git.root or os.getcwd()
        program_relative: str = self.settings.program_relpath
        filesystem.mkdir_exists_ok(
            os.path.join(
                self.settings.files_dir, "code", os.path.dirname(program_relative)
            )
        )
        program_absolute = os.path.join(root, program_relative)
        if not os.path.exists(program_absolute):
            logger.warning(
                "unable to save code -- can't find {}".format(program_absolute)
            )
            return None
        saved_program = os.path.join(self.settings.files_dir, "code", program_relative)
        self.saved_program = program_relative  # type: ignore

        if not os.path.exists(saved_program):
            copyfile(program_absolute, saved_program)
        logger.debug("Saving code done")

    def _save_patches(self) -> None:
        """Save the current state of this repository to one or more patches.

        Makes one patch against HEAD and another one against the most recent
        commit that occurs in an upstream branch. This way we can be robust
        to history editing as long as the user never does "push -f" to break
        history on an upstream branch.

        Writes the first patch to <files_dir>/<DIFF_FNAME> and the second to
        <files_dir>/upstream_diff_<commit_id>.patch.

        """
        if not self.git.enabled:
            return None

        logger.debug("Saving git patches")
        try:
            root = self.git.root
            diff_args = ["git", "diff"]
            if self.git.has_submodule_diff:
                diff_args.append("--submodule=diff")

            if self.git.dirty:
                patch_path = os.path.join(self.settings.files_dir, DIFF_FNAME)
                with open(patch_path, "wb") as patch:
                    # we diff against HEAD to ensure we get changes in the index
                    subprocess.check_call(
                        diff_args + ["HEAD"], stdout=patch, cwd=root, timeout=5
                    )
                    self.saved_patches.append(
                        os.path.relpath(patch_path, start=self.settings.files_dir)
                    )

            upstream_commit = self.git.get_upstream_fork_point()
            if upstream_commit and upstream_commit != self.git.repo.head.commit:  # type: ignore
                sha = upstream_commit.hexsha
                upstream_patch_path = os.path.join(
                    self.settings.files_dir, f"upstream_diff_{sha}.patch"
                )
                with open(upstream_patch_path, "wb") as upstream_patch:
                    subprocess.check_call(
                        diff_args + [sha], stdout=upstream_patch, cwd=root, timeout=5
                    )
                    self.saved_patches.append(
                        os.path.relpath(
                            upstream_patch_path, start=self.settings.files_dir
                        )
                    )
        # TODO: A customer saw `ValueError: Reference at 'refs/remotes/origin/foo'
        #  does not exist` so we now catch ValueError. Catching this error feels
        #  too generic.
        except (
            ValueError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as e:
            logger.error("Error generating diff: {}".format(e))
        logger.debug("Saving git patches done")

    def _probe_git(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.settings.disable_git:
            return data

        # in case of manually passing the git repo info, `enabled` would be False,
        # but we still want to save the git repo info
        if not self.git.enabled and self.git.auto:
            return data

        logger.debug("Probing git")

        data["git"] = {
            "remote": self.git.remote_url,
            "commit": self.git.last_commit,
        }
        data["email"] = self.git.email
        data["root"] = self.git.root or data.get("root") or os.getcwd()
        logger.debug("Probing git done")

        return data

    def probe(self) -> Dict[str, Any]:
        """Probe the system for information about the current environment."""
        # todo: refactor this quality code 🤮🤮🤮🤮🤮
        logger.debug("Probing system")
        data: Dict[str, Any] = dict()

        data["os"] = self.settings._os
        data["python"] = self.settings._python
        data["heartbeatAt"] = datetime.datetime.utcnow().isoformat()
        data["startedAt"] = datetime.datetime.utcfromtimestamp(
            self.settings._start_time
        ).isoformat()

        data["docker"] = self.settings.docker

        data["cuda"] = self.settings._cuda
        data["args"] = tuple(self.settings._args or ())
        data["state"] = "running"

        if self.settings.program is not None:
            data["program"] = self.settings.program
            # Used during artifact-job creation, always points to the relpath
            # of code execution, even when in a git repo
            data["codePathLocal"] = self.settings._code_path_local
        if not self.settings.disable_code:
            if self.settings.program_relpath:
                data["codePath"] = self.settings.program_relpath
            elif self.settings._jupyter:
                if self.settings.notebook_name:
                    data["program"] = self.settings.notebook_name
                elif self.settings._jupyter_path:
                    if self.settings._jupyter_path.startswith("fileId="):
                        unescaped = unquote(self.settings._jupyter_path)
                        data["colab"] = (
                            "https://colab.research.google.com/notebook#" + unescaped
                        )
                        data["program"] = self.settings._jupyter_name
                    else:
                        data["program"] = self.settings._jupyter_path
                        data["root"] = self.settings._jupyter_root
            # get the git repo info
            data = self._probe_git(data)

        if self.settings.anonymous != "true":
            data["host"] = self.settings.host
            data["username"] = self.settings.username
            data["executable"] = sys.executable
        else:
            data.pop("email", None)
            data.pop("root", None)

        logger.debug("Probing system done")

        return data

    def _save_conda(self) -> None:
        current_shell_is_conda = os.path.exists(os.path.join(sys.prefix, "conda-meta"))
        if not current_shell_is_conda:
            return None

        logger.debug(
            "Saving list of conda packages installed into the current environment"
        )
        try:
            with open(
                os.path.join(self.settings.files_dir, CONDA_ENVIRONMENTS_FNAME), "w"
            ) as f:
                subprocess.call(
                    ["conda", "env", "export"],
                    stdout=f,
                    stderr=subprocess.DEVNULL,
                    timeout=15,  # add timeout since conda env export could take a really long time
                )
        except Exception as e:
            logger.exception(f"Error saving conda packages: {e}")
        logger.debug("Saving conda packages done")

    def publish(self, system_info: dict) -> None:
        # save pip, conda, code patches to disk
        if self.settings._save_requirements:
            self._save_conda()
        if self.settings.save_code:
            self._save_code()
            self._save_patches()

        # save system_info to disk
        with open(self.metadata_file_name, "w") as f:
            s = json.dumps(system_info, indent=4)
            f.write(s)
            f.write("\n")
        base_name = os.path.basename(self.metadata_file_name)
        files = dict(files=[(base_name, "now")])

        if self.saved_program:
            saved_program = os.path.join("code", self.saved_program)
            files["files"].append((glob.escape(saved_program), "now"))
        for patch in self.saved_patches:
            files["files"].append((glob.escape(patch), "now"))

        # publish files to the backend
        self.backend_interface.publish_files(files)  # type: ignore
