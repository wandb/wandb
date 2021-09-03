#
# -*- coding: utf-8 -*-
"""
meta.
"""

from datetime import datetime
import json
import logging
import multiprocessing
import os
from shutil import copyfile
import sys
from urllib.parse import unquote

from wandb import util
from wandb.vendor.pynvml import pynvml

from ..lib.filenames import (
    CONDA_ENVIRONMENTS_FNAME,
    DIFF_FNAME,
    METADATA_FNAME,
    REQUIREMENTS_FNAME,
)
from ..lib.git import GitRepo

if os.name == "posix" and sys.version_info[0] < 3:
    import subprocess32 as subprocess  # type: ignore[import]
else:
    import subprocess  # type: ignore[no-redef]


logger = logging.getLogger(__name__)


class Meta(object):
    """Used to store metadata during and after a run."""

    def __init__(self, settings=None, interface=None):
        logger.debug("meta init")
        self._settings = settings
        self.data = {}
        self.fname = os.path.join(self._settings.files_dir, METADATA_FNAME)
        self._interface = interface
        self._git = GitRepo(
            remote=self._settings["git_remote"]
            if "git_remote" in self._settings.keys()
            else "origin"
        )
        # Location under "code" directory in files where program was saved.
        self._saved_program = None
        # Locations under files directory where diff patches were saved.
        self._saved_patches = []
        logger.debug("meta init done")

    def _save_pip(self):
        """Saves the current working set of pip packages to {REQUIREMENTS_FNAME}"""
        logger.debug("save pip")
        try:
            import pkg_resources

            installed_packages = [d for d in iter(pkg_resources.working_set)]
            installed_packages_list = sorted(
                ["%s==%s" % (i.key, i.version) for i in installed_packages]
            )
            with open(
                os.path.join(self._settings.files_dir, REQUIREMENTS_FNAME), "w"
            ) as f:
                f.write("\n".join(installed_packages_list))
        except Exception:
            logger.exception("Error saving pip packages")
        logger.debug("save pip done")

    def _save_conda(self):
        current_shell_is_conda = os.path.exists(os.path.join(sys.prefix, "conda-meta"))
        if not current_shell_is_conda:
            return False

        logger.debug("save conda")
        try:
            with open(
                os.path.join(self._settings.files_dir, CONDA_ENVIRONMENTS_FNAME), "w"
            ) as f:
                subprocess.call(["conda", "env", "export"], stdout=f)
        except Exception:
            logger.exception("Error saving conda packages")
        logger.debug("save conda done")

    def _save_code(self):
        logger.debug("save code")
        if self._settings.program_relpath is None:
            logger.warning("unable to save code -- program entry not found")
            return

        root = self._git.root or os.getcwd()
        program_relative = self._settings.program_relpath
        util.mkdir_exists_ok(
            os.path.join(
                self._settings.files_dir, "code", os.path.dirname(program_relative)
            )
        )
        program_absolute = os.path.join(root, program_relative)
        if not os.path.exists(program_absolute):
            logger.warning("unable to save code -- can't find %s" % program_absolute)
            return
        saved_program = os.path.join(self._settings.files_dir, "code", program_relative)
        self._saved_program = program_relative

        if not os.path.exists(saved_program):
            copyfile(program_absolute, saved_program)
        logger.debug("save code done")

    def _save_patches(self):
        """Save the current state of this repository to one or more patches.

        Makes one patch against HEAD and another one against the most recent
        commit that occurs in an upstream branch. This way we can be robust
        to history editing as long as the user never does "push -f" to break
        history on an upstream branch.

        Writes the first patch to <files_dir>/<DIFF_FNAME> and the second to
        <files_dir>/upstream_diff_<commit_id>.patch.

        """
        if not self._git.enabled:
            return False

        logger.debug("save patches")
        try:
            root = self._git.root
            diff_args = ["git", "diff"]
            if self._git.has_submodule_diff:
                diff_args.append("--submodule=diff")

            if self._git.dirty:
                patch_path = os.path.join(self._settings.files_dir, DIFF_FNAME)
                with open(patch_path, "wb") as patch:
                    # we diff against HEAD to ensure we get changes in the index
                    subprocess.check_call(
                        diff_args + ["HEAD"], stdout=patch, cwd=root, timeout=5
                    )
                    self._saved_patches.append(
                        os.path.relpath(patch_path, start=self._settings.files_dir)
                    )

            upstream_commit = self._git.get_upstream_fork_point()
            if upstream_commit and upstream_commit != self._git.repo.head.commit:
                sha = upstream_commit.hexsha
                upstream_patch_path = os.path.join(
                    self._settings.files_dir, "upstream_diff_{}.patch".format(sha)
                )
                with open(upstream_patch_path, "wb") as upstream_patch:
                    subprocess.check_call(
                        diff_args + [sha], stdout=upstream_patch, cwd=root, timeout=5
                    )
                    self._saved_patches.append(
                        os.path.relpath(
                            upstream_patch_path, start=self._settings.files_dir
                        )
                    )
        # TODO: A customer saw `ValueError: Reference at 'refs/remotes/origin/foo'
        # does not exist` so we now catch ValueError. Catching this error feels
        # too generic.
        except (
            ValueError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as e:
            logger.error("Error generating diff: %s" % e)
        logger.debug("save patches done")

    def _setup_sys(self):
        self.data["os"] = self._settings._os
        self.data["python"] = self._settings._python
        self.data["heartbeatAt"] = datetime.utcnow().isoformat()
        self.data["startedAt"] = datetime.utcfromtimestamp(
            self._settings._start_time
        ).isoformat()

        self.data["docker"] = self._settings.docker

        try:
            pynvml.nvmlInit()
            self.data["gpu"] = pynvml.nvmlDeviceGetName(
                pynvml.nvmlDeviceGetHandleByIndex(0)
            ).decode("utf8")
            self.data["gpu_count"] = pynvml.nvmlDeviceGetCount()
        except pynvml.NVMLError:
            pass
        try:
            self.data["cpu_count"] = multiprocessing.cpu_count()
        except NotImplementedError:
            pass

        self.data["cuda"] = self._settings._cuda
        self.data["args"] = self._settings._args
        self.data["state"] = "running"

    def _setup_git(self):
        if self._git.enabled:
            logger.debug("setup git")
            self.data["git"] = {
                "remote": self._git.remote_url,
                "commit": self._git.last_commit,
            }
            self.data["email"] = self._git.email
            self.data["root"] = self._git.root or self.data["root"] or os.getcwd()
            logger.debug("setup git done")

    def probe(self):
        logger.debug("probe")
        self._setup_sys()
        if self._settings.program is not None:
            self.data["program"] = self._settings.program
        if not self._settings.disable_code:
            if self._settings.program_relpath is not None:
                self.data["codePath"] = self._settings.program_relpath
            elif self._settings._jupyter:
                if self._settings.notebook_name:
                    self.data["program"] = self._settings.notebook_name
                elif self._settings._jupyter_path:
                    if self._settings._jupyter_path.startswith("fileId="):
                        unescaped = unquote(self._settings._jupyter_path)
                        self.data["colab"] = (
                            "https://colab.research.google.com/notebook#"
                            + unescaped  # noqa
                        )
                        self.data["program"] = self._settings._jupyter_name
                    else:
                        self.data["program"] = self._settings._jupyter_path
                        self.data["root"] = self._settings._jupyter_root
            self._setup_git()

        if self._settings.anonymous != "true":
            self.data["host"] = self._settings.host
            self.data["username"] = self._settings.username
            self.data["executable"] = sys.executable
        else:
            self.data.pop("email", None)
            self.data.pop("root", None)

        if self._settings.save_code:
            self._save_code()
            self._save_patches()

        if self._settings._save_requirements:
            self._save_pip()
            self._save_conda()
        logger.debug("probe done")

    def write(self):
        with open(self.fname, "w") as f:
            s = json.dumps(self.data, indent=4)
            f.write(s)
            f.write("\n")
        base_name = os.path.basename(self.fname)
        files = dict(files=[(base_name, "now")])

        if self._saved_program:
            saved_program = os.path.join("code", self._saved_program)
            files["files"].append((saved_program, "now"))
        for patch in self._saved_patches:
            files["files"].append((patch, "now"))

        self._interface.publish_files(files)
