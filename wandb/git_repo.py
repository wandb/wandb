from git import Repo, exc
import os

class GitRepo(object):
    def __init__(self, root=None, remote="origin", lazy=True):
        self.remote_name = remote
        self.root = root
        self._repo = None
        if not lazy:
            self.repo

    @property
    def repo(self):
        if self._repo is None:
            if self.remote_name is None:
                self._repo = False
            else:
                try:
                    self._repo = Repo(self.root or os.getcwd(), search_parent_directories=True)
                except exc.InvalidGitRepositoryError:
                    self._repo = False
        return self._repo
    
    @property
    def enabled(self):
        return self.repo

    @property
    def dirty(self):
        if not self.repo:
            return False
        return self.repo.is_dirty()

    @property
    def last_commit(self):
        if not self.repo:
            return None
        return self.repo.head.commit.hexsha

    @property
    def branch(self):
        if not self.repo:
            return None
        return self.repo.head.ref.name

    @property
    def remote(self):
        if not self.repo:
            return None
        try:
            return self.repo.remotes[self.remote_name]
        except IndexError:
            return None

    @property
    def remote_url(self):
        if not self.remote:
            return None
        return self.remote.url

    def tag(self, name, message):
        try:
            return self.repo.create_tag("wandb/"+name, message=message, force=True)
        except exc.GitCommandError:
            print("Failed to tag repository.")
            return None

    def push(self, name):
        if self.remote:
            try:
                return self.remote.push("wandb/"+name, force=True)
            except exc.GitCommandError:
                return None
