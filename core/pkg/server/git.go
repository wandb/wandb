package server

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	git "github.com/go-git/go-git/v5"
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

/*
Get diff of current working tree vs uncommitted changes
git diff HEAD

If there are submodules, you can use the --submodule=diff option to make git diff recurse into them:
git diff HEAD --submodule=diff

To check if there are submodules:
git submodule status
(should return nothing if there are no submodules)

Get diff of current working tree vs last commit on upstream branch
git diff @{u}
*/

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

func (g *Git) Probe() {
	filesDirPath := g.settings.GetFilesDir().GetValue()
	repoPath := "."

	// check if repoPath is a git repository
	_, err := git.PlainOpen(repoPath)
	if err != nil {
		fmt.Println("Error opening repository:", err)
		return
	}

	// check if there are submodules
	command := []string{"git", "submodule", "status"}
	output, err := runCommandWithOutput(command, repoPath)
	var hasSubmodules bool
	if err != nil {
		fmt.Println("Error checking submodules:", err)
	}
	hasSubmodules = len(output) > 0

	// get diff of current working tree vs uncommitted changes
	command = []string{"git", "diff", "HEAD"}
	if hasSubmodules {
		command = append(command, "--submodule=diff")
	}
	err = runCommand(command, repoPath, filepath.Join(filesDirPath, diffFileName))
	if err != nil {
		fmt.Println("Error generating diff:", err)
	}

	// Get the latest commit of the upstream branch
	command = []string{"git", "rev-parse", "@{u}"}
	output, err = runCommandWithOutput(command, repoPath)
	if err != nil {
		fmt.Println("Error getting latest commit of upstream branch:", err)
		return
	}

	// get diff of current working tree vs last commit on upstream branch
	command = []string{"git", "diff", "@{u}"}
	if hasSubmodules {
		command = append(command, "--submodule=diff")
	}
	outFile := fmt.Sprintf("diff_%s.patch", strings.TrimSpace(string(output)))
	err = runCommand(
		command,
		repoPath,
		filepath.Join(filesDirPath, outFile),
	)
	if err != nil {
		fmt.Println("Error generating diff:", err)
	}
}
