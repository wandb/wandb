package server

import (
	"fmt"
	"os"
	"path/filepath"

	git "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
	"github.com/wandb/wandb/core/pkg/service"
)

const diffFileName = "diff.patch"

type Git struct {
	name     string
	settings *service.Settings
}

func NewGit(settings *service.Settings) *Git {
	return &Git{
		name:     "git",
		settings: settings,
	}
}

func (g *Git) IsAvailable() bool { return true }

func (g *Git) Probe() {
	filesDirPath := g.settings.GetFilesDir().GetValue()
	repoPath := "."
	repo, err := git.PlainOpen(repoPath)
	if err != nil {
		fmt.Println("Error opening repository:", err)
		return
	}

	err = generateAndSaveDiff(repo, filesDirPath, diffFileName)
	if err != nil {
		fmt.Println("Error generating diff:", err)
	}
}

func generateAndSaveDiff(repo *git.Repository, filesDirPath, fileName string) error {
	headRef, err := repo.Head()
	if err != nil {
		return err
	}

	headCommit, err := repo.CommitObject(headRef.Hash())
	if err != nil {
		return err
	}

	headTree, err := headCommit.Tree()
	if err != nil {
		return err
	}

	// Obtain the commit to compare with (e.g., the parent commit)
	commitToCompare, err := headCommit.Parents().Next()
	if err != nil {
		return err
	}

	compareTree, err := commitToCompare.Tree()
	if err != nil {
		return err
	}

	// Generate the diff
	diff, err := object.DiffTree(compareTree, headTree)
	if err != nil {
		return err
	}

	// Create and write diff to file
	diffFilePath := filepath.Join(filesDirPath, fileName)
	return writeDiffToFile(diff, diffFilePath)
}

func writeDiffToFile(diff object.Changes, path string) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	for _, change := range diff {
		action, err := change.Action()
		if err != nil {
			return err
		}
		fmt.Fprintf(file, "%s: %s\n", action, change.To.Name)
	}

	return nil
}
