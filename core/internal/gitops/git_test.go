package gitops_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/config"
	"github.com/go-git/go-git/v5/plumbing"
	"github.com/go-git/go-git/v5/plumbing/object"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gitops"

	"github.com/wandb/wandb/core/internal/observability"
)

func setupTestRepo() (string, *git.Repository, func(), error) {
	repoPath, err := os.MkdirTemp("", "testrepo")
	if err != nil {
		return "", nil, nil, err
	}
	repo, err := git.PlainInit(repoPath, false)
	if err != nil {
		return "", nil, nil, err
	}

	worktree, err := repo.Worktree()
	if err != nil {
		return "", nil, nil, err
	}
	tempFile := filepath.Join(repoPath, "temp.txt")
	err = os.WriteFile(tempFile, []byte("test content"), 0644)
	if err != nil {
		return "", nil, nil, err
	}

	_, err = worktree.Add("temp.txt")
	if err != nil {
		return "", nil, nil, err
	}

	commit, err := worktree.Commit("Initial commit", &git.CommitOptions{
		Author: &object.Signature{
			Name:  "Test User",
			Email: "test@example.com",
		},
	})
	if err != nil {
		return "", nil, nil, err
	}
	fmt.Printf("Commit created: %s\n", commit.String())

	cleanup := func() {
		_ = os.RemoveAll(repoPath)
	}
	return repoPath, repo, cleanup, nil
}

func initializeAndAddRemoteRepo(baseRepo *git.Repository) (string, *git.Repository, func(), error) {
	// Create and initialize a bare remote repo
	remoteRepoPath, err := os.MkdirTemp("", "remoterepo")
	if err != nil {
		_ = os.RemoveAll(remoteRepoPath)
		return "", nil, nil, err
	}

	repo, err := git.PlainInit(remoteRepoPath, true)
	if err != nil {
		_ = os.RemoveAll(remoteRepoPath)
		return "", nil, nil, err
	}

	_, _ = baseRepo.CreateRemote(&config.RemoteConfig{
		Name: "origin",
		URLs: []string{remoteRepoPath},
	})

	_ = baseRepo.Push(&git.PushOptions{
		RemoteName: "origin",
	})

	_, err = baseRepo.Remote("origin")
	if err != nil {
		_ = os.RemoveAll(remoteRepoPath)
		return "", nil, nil, err
	}

	cleanup := func() {
		_ = os.RemoveAll(remoteRepoPath)
	}
	return remoteRepoPath, repo, cleanup, nil
}

func addAndCommitWithContent(
	repo *git.Repository,
	file string,
	content string,
) (string, error) {
	worktree, err := repo.Worktree()
	if err != nil {
		return "", err
	}

	err = os.WriteFile(
		filepath.Join(worktree.Filesystem.Root(), file),
		[]byte(content),
		0644,
	)
	if err != nil {
		return "", err
	}

	_, err = worktree.Add(file)
	if err != nil {
		return "", err
	}

	commit, err := worktree.Commit(content, &git.CommitOptions{
		Author: &object.Signature{
			Name:  "Test User",
			Email: "test@example.com",
		},
	})
	if err != nil {
		return "", err
	}

	return commit.String(), nil
}

func TestIsAvailable(t *testing.T) {
	repoPath, _, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	logger := observability.NewNoOpLogger()
	git := gitops.New(repoPath, logger)
	available := git.IsAvailable()
	assert.True(t, available)
}

func TestLatestCommit(t *testing.T) {
	repoPath, _, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	logger := observability.NewNoOpLogger()
	git := gitops.New(repoPath, logger)
	latest, err := git.LatestCommit("HEAD")
	assert.NoError(t, err)
	assert.Len(t, latest, 40)
}

func TestSavePatch(t *testing.T) {
	repoPath, _, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	// append a line to the temp.txt file
	tempFile := filepath.Join(repoPath, "temp.txt")
	err = os.WriteFile(tempFile, []byte("test content\n"), 0644)
	if err != nil {
		t.Fatal(err)
	}

	tempDir, err := os.MkdirTemp("", "temp_output")
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		_ = os.RemoveAll(tempDir)
	}()
	outputPath := filepath.Join(tempDir, "diff.patch")

	logger := observability.NewNoOpLogger()
	git := gitops.New(repoPath, logger)
	err = git.SavePatch("HEAD", outputPath)
	assert.NoError(t, err)
	assert.FileExists(t, outputPath)
	// check that the patch file contains the new line
	patch, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	assert.Contains(t, string(patch), "+test content")
}

func TestGetUpstreamForkPoint_NoTrackingBranch(t *testing.T) {
	repoPath, _, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	logger := observability.NewNoOpLogger()
	gitOps := gitops.New(repoPath, logger)
	forkPoint, err := gitOps.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Empty(t, forkPoint)
}

func TestGetUpstreamForkPoint_UpstreamSet(t *testing.T) {
	baseRepoPath, baseRepo, baseRepoCleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer baseRepoCleanup()
	_, remoteRepo, remoteRepoCleanup, err := initializeAndAddRemoteRepo(baseRepo)
	if err != nil {
		t.Fatal(err)
	}
	defer remoteRepoCleanup()

	// setup and push to remote repo
	_ = baseRepo.CreateBranch(&config.Branch{
		Name:   "master",
		Remote: "origin",
		Merge:  plumbing.ReferenceName("refs/heads/master"),
	})
	_ = baseRepo.Push(&git.PushOptions{
		RemoteName: "origin",
	})

	remoteRepoHead, err := remoteRepo.Head()
	if err != nil {
		t.Fatal(err)
	}

	// Make a commit to the base repo not pushed to remote
	commit, err := addAndCommitWithContent(baseRepo, "temp2.txt", "test content")
	if err != nil {
		t.Fatal(err)
	}

	logger := observability.NewNoOpLogger()
	gitOps := gitops.New(baseRepoPath, logger)
	forkPoint, err := gitOps.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.NotEmpty(t, forkPoint)
	assert.Equal(t, remoteRepoHead.Hash().String(), forkPoint)
	assert.NotEqual(t, commit, forkPoint)
}

func TestGetUpstreamForkPoint_NoTrackingBranchFindsMostRecentAncestor(t *testing.T) {
	repoPath, baseRepo, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	_, _, remoteRepoCleanup, err := initializeAndAddRemoteRepo(baseRepo)
	if err != nil {
		t.Fatal(err)
	}
	defer remoteRepoCleanup()

	// Create master tracking branch
	_ = baseRepo.CreateBranch(&config.Branch{
		Name:   "master",
		Remote: "origin",
		Merge:  plumbing.ReferenceName("refs/heads/master"),
	})
	_ = baseRepo.Push(&git.PushOptions{
		RemoteName: "origin",
	})

	// Checkout new branch with no tracking information
	worktree, _ := baseRepo.Worktree()
	_ = worktree.Checkout(&git.CheckoutOptions{
		Branch: plumbing.NewBranchReferenceName("feature"),
		Create: true,
	})

	// Add a commit on the feature branch
	commit, _ := addAndCommitWithContent(baseRepo, "feature.txt", "feature branch content")
	if err != nil {
		t.Fatal(err)
	}

	logger := observability.NewNoOpLogger()
	gitOps := gitops.New(repoPath, logger)
	forkPoint, err := gitOps.GetUpstreamForkPoint()

	masterHead, _ := baseRepo.Reference(plumbing.ReferenceName("refs/remotes/origin/master"), true)
	currentBranchHead, _ := baseRepo.Head()
	assert.NoError(t, err)
	assert.NotEmpty(t, forkPoint)
	assert.Equal(t, masterHead.Hash().String(), forkPoint)
	assert.NotEqual(t, commit, forkPoint)
	assert.NotEqual(t, currentBranchHead.Hash().String(), forkPoint)
}

func TestGetUpstreamForkPoint_DetachedHead(t *testing.T) {
	repoPath, baseRepo, baseRepoCleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer baseRepoCleanup()
	_, _, remoteRepoCleanup, err := initializeAndAddRemoteRepo(baseRepo)
	if err != nil {
		t.Fatal(err)
	}
	defer remoteRepoCleanup()

	// Checkout the HEAD commit in detached head state
	head, _ := baseRepo.Head()
	worktree, _ := baseRepo.Worktree()
	err = worktree.Checkout(&git.CheckoutOptions{
		Hash: head.Hash(),
	})
	if err != nil {
		t.Fatal(err)
	}

	logger := observability.NewNoOpLogger()
	gitOps := gitops.New(repoPath, logger)
	forkPoint, err := gitOps.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.Empty(t, forkPoint)
}

func TestGetUpstreamForkPoint_MultipleTrackingBranches(t *testing.T) {
	repoPath, baseRepo, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	_, _, remoteRepoCleanup, err := initializeAndAddRemoteRepo(baseRepo)
	if err != nil {
		t.Fatal(err)
	}
	defer remoteRepoCleanup()

	worktree, _ := baseRepo.Worktree()

	// Create multiple branches with tracking information
	for _, branch := range []string{"feature1", "feature2", "feature3"} {
		_ = worktree.Checkout(&git.CheckoutOptions{
			Branch: plumbing.NewBranchReferenceName(branch),
			Create: true,
		})
		_ = baseRepo.CreateBranch(&config.Branch{
			Name:   branch,
			Remote: "origin",
			Merge:  plumbing.ReferenceName(fmt.Sprintf("refs/heads/%s", branch)),
		})
		_, _ = addAndCommitWithContent(baseRepo, branch+".txt", "feature content")
		_ = baseRepo.Push(&git.PushOptions{
			RemoteName: "origin",
		})

	}

	// Create a new branch based on feature2 branch HEAD
	branch2Head, _ := baseRepo.Reference(plumbing.ReferenceName("refs/remotes/origin/feature2"), true)
	_ = worktree.Checkout(&git.CheckoutOptions{
		Hash:   branch2Head.Hash(),
		Branch: plumbing.NewBranchReferenceName("feature4"),
		Create: true,
	})

	// Add a commit on the new branch
	commit, _ := addAndCommitWithContent(baseRepo, "newbranch.txt", "new branch content")
	if err != nil {
		t.Fatal(err)
	}

	logger := observability.NewNoOpLogger()
	gitOps := gitops.New(repoPath, logger)
	forkPoint, err := gitOps.GetUpstreamForkPoint()

	assert.NoError(t, err)
	assert.NotEmpty(t, forkPoint)
	assert.NotEqual(t, commit, forkPoint)
	assert.Equal(t, branch2Head.Hash().String(), forkPoint)
	branch1Head, _ := baseRepo.Reference(plumbing.ReferenceName("refs/remotes/origin/feature1"), true)
	branch3Head, _ := baseRepo.Reference(plumbing.ReferenceName("refs/remotes/origin/feature3"), true)
	assert.NotEqual(t, branch1Head.Hash().String(), forkPoint)
	assert.NotEqual(t, branch3Head.Hash().String(), forkPoint)
}
