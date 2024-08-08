package server_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/server"
)

func setupTestRepo() (string, func(), error) {
	repoPath, err := os.MkdirTemp("", "testrepo")
	if err != nil {
		return "", nil, err
	}
	repo, err := git.PlainInit(repoPath, false)
	if err != nil {
		return "", nil, err
	}

	worktree, err := repo.Worktree()
	if err != nil {
		return "", nil, err
	}
	tempFile := filepath.Join(repoPath, "temp.txt")
	err = os.WriteFile(tempFile, []byte("test content"), 0644)
	if err != nil {
		return "", nil, err
	}

	_, err = worktree.Add("temp.txt")
	if err != nil {
		return "", nil, err
	}

	commit, err := worktree.Commit("Initial commit", &git.CommitOptions{
		Author: &object.Signature{
			Name:  "Test User",
			Email: "test@example.com",
		},
	})
	if err != nil {
		return "", nil, err
	}
	fmt.Printf("Commit created: %s\n", commit.String())

	cleanup := func() {
		os.RemoveAll(repoPath)
	}
	return repoPath, cleanup, nil
}

func TestIsAvailable(t *testing.T) {
	repoPath, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	logger := observability.NewNoOpLogger()
	git := server.NewGit(repoPath, logger)
	available := git.IsAvailable()
	assert.True(t, available)
}

func TestLatestCommit(t *testing.T) {
	repoPath, cleanup, err := setupTestRepo()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()

	logger := observability.NewNoOpLogger()
	git := server.NewGit(repoPath, logger)
	latest, err := git.LatestCommit("HEAD")
	assert.NoError(t, err)
	assert.Len(t, latest, 40)
}

func TestSavePatch(t *testing.T) {
	repoPath, cleanup, err := setupTestRepo()
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
	defer os.RemoveAll(tempDir)
	outputPath := filepath.Join(tempDir, "diff.patch")

	logger := observability.NewNoOpLogger()
	git := server.NewGit(repoPath, logger)
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
