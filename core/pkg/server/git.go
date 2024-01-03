package server

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	git "github.com/go-git/go-git/v5"
	"github.com/wandb/wandb/core/pkg/observability"
)

func runCommand(command []string, dir, outFile string) error {
	output, err := runCommandWithOutput(command, dir)
	if err != nil {
		return err
	}
	if len(output) > 0 {
		f, err := os.Create(outFile)
		if err != nil {
			return err
		}
		defer f.Close()
		_, err = f.Write(output)
		if err != nil {
			return err
		}
	}
	return nil
}

func runCommandWithOutput(command []string, dir string) ([]byte, error) {
	cmd := exec.Command(command[0], command[1:]...)
	cmd.Dir = dir
	return cmd.CombinedOutput()
}

type Git struct {
	path   string
	logger *observability.CoreLogger
}

func NewGit(path string, logger *observability.CoreLogger) *Git {
	return &Git{
		path:   path,
		logger: logger,
	}
}

func (g *Git) IsAvailable() bool {
	// check if repoPath is a git repository
	if _, err := git.PlainOpen(g.path); err != nil {
		g.logger.Error("git repo not found", "error", err)
		return false
	}
	return true
}

func (g *Git) LatestCommit(ref string) (string, error) {
	// get latest commit
	command := []string{"git", "rev-parse", ref}
	output, err := runCommandWithOutput(command, g.path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// SavePatch saves a patch file of the diff between the current working tree and
// the given ref. Returns an error if the operation fails, or if no diff is found.
func (g *Git) SavePatch(ref, output string) error {
	// get diff of current working tree vs uncommitted changes
	command := []string{"git", "diff", ref, "--submodule=diff"}
	err := runCommand(command, g.path, output)
	if err != nil {
		return err
	}
	// check if a file was created
	if _, err := os.Stat(output); os.IsNotExist(err) {
		return fmt.Errorf("no diff found")
	}
	return nil
}
