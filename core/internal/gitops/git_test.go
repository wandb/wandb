package gitops_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gitops"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
)

// git runs a git command in dir and returns its trimmed output.
func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(),
		"GIT_CONFIG_GLOBAL=/dev/null",
		"GIT_CONFIG_NOSYSTEM=1",
		"GIT_AUTHOR_NAME=Test User",
		"GIT_AUTHOR_EMAIL=test@example.com",
		"GIT_COMMITTER_NAME=Test User",
		"GIT_COMMITTER_EMAIL=test@example.com",
	)
	out, err := cmd.CombinedOutput()
	require.NoError(t, err, "git %s: %s", strings.Join(args, " "), out)
	return strings.TrimSpace(string(out))
}

// commitFile writes a file, commits it, and returns the commit hash.
func commitFile(t *testing.T, repoPath, name, content string) string {
	t.Helper()
	require.NoError(t, os.WriteFile(filepath.Join(repoPath, name), []byte(content), 0o644))
	git(t, repoPath, "add", name)
	git(t, repoPath, "commit", "-m", content)
	return git(t, repoPath, "rev-parse", "HEAD")
}

// setupTestRepo creates a repository with one commit on master.
func setupTestRepo(t *testing.T) string {
	t.Helper()
	repoPath := t.TempDir()
	git(t, repoPath, "init", "-b", "master")
	commitFile(t, repoPath, "temp.txt", "test content")
	return repoPath
}

// addRemote adds a bare repository as origin and pushes master to it without tracking.
func addRemote(t *testing.T, repoPath string) {
	t.Helper()
	remotePath := t.TempDir()
	git(t, remotePath, "init", "--bare")
	git(t, repoPath, "remote", "add", "origin", remotePath)
	git(t, repoPath, "push", "origin", "master")
}

func TestIsAvailable(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)

	assert.True(t, gitops.New(setupTestRepo(t), logger).IsAvailable())
	assert.False(t, gitops.New(t.TempDir(), logger).IsAvailable())
}

func TestLatestCommit(t *testing.T) {
	g := gitops.New(setupTestRepo(t), observabilitytest.NewTestLogger(t))

	latest, err := g.LatestCommit("HEAD")

	assert.NoError(t, err)
	assert.Len(t, latest, 40)
}

func TestSavePatch(t *testing.T) {
	repoPath := setupTestRepo(t)
	tempFile := filepath.Join(repoPath, "temp.txt")
	require.NoError(t, os.WriteFile(tempFile, []byte("test content\n"), 0o644))
	outputPath := filepath.Join(t.TempDir(), "diff.patch")
	g := gitops.New(repoPath, observabilitytest.NewTestLogger(t))

	err := g.SavePatch("HEAD", outputPath)

	assert.NoError(t, err)
	patch, err := os.ReadFile(outputPath)
	require.NoError(t, err)
	assert.Contains(t, string(patch), "+test content")
}

func TestGetUpstreamForkPoint_NoTrackingBranch(t *testing.T) {
	g := gitops.New(setupTestRepo(t), observability.NewNoOpLogger())

	forkPoint, err := g.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Empty(t, forkPoint)
}

func TestGetUpstreamForkPoint_UpstreamSet(t *testing.T) {
	repoPath := setupTestRepo(t)
	addRemote(t, repoPath)
	git(t, repoPath, "branch", "--set-upstream-to=origin/master")
	remoteHead := git(t, repoPath, "rev-parse", "origin/master")
	commit := commitFile(t, repoPath, "temp2.txt", "test content")
	g := gitops.New(repoPath, observability.NewNoOpLogger())

	forkPoint, err := g.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Equal(t, remoteHead, forkPoint)
	assert.NotEqual(t, commit, forkPoint)
}

func TestGetUpstreamForkPoint_NoTrackingBranchFindsMostRecentAncestor(t *testing.T) {
	repoPath := setupTestRepo(t)
	addRemote(t, repoPath)
	git(t, repoPath, "branch", "--set-upstream-to=origin/master")
	git(t, repoPath, "checkout", "--no-track", "-b", "feature")
	commit := commitFile(t, repoPath, "feature.txt", "feature branch content")
	g := gitops.New(repoPath, observability.NewNoOpLogger())

	forkPoint, err := g.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Equal(t, git(t, repoPath, "rev-parse", "origin/master"), forkPoint)
	assert.NotEqual(t, commit, forkPoint)
}

func TestGetUpstreamForkPoint_DetachedHead(t *testing.T) {
	repoPath := setupTestRepo(t)
	addRemote(t, repoPath)
	git(t, repoPath, "checkout", "--detach")
	g := gitops.New(repoPath, observability.NewNoOpLogger())

	forkPoint, err := g.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Empty(t, forkPoint)
}

func TestGetUpstreamForkPoint_MultipleTrackingBranches(t *testing.T) {
	repoPath := setupTestRepo(t)
	addRemote(t, repoPath)
	for _, branch := range []string{"feature1", "feature2", "feature3"} {
		git(t, repoPath, "checkout", "-b", branch)
		commitFile(t, repoPath, branch+".txt", "feature content")
		git(t, repoPath, "push", "-u", "origin", branch)
	}
	git(t, repoPath, "checkout", "--no-track", "-b", "feature4", "origin/feature2")
	commit := commitFile(t, repoPath, "newbranch.txt", "new branch content")
	g := gitops.New(repoPath, observability.NewNoOpLogger())

	forkPoint, err := g.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Equal(t, git(t, repoPath, "rev-parse", "origin/feature2"), forkPoint)
	assert.NotEqual(t, commit, forkPoint)
}
