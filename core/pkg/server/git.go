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
	path     string
	settings *service.Settings
}

func NewGit(path string, settings *service.Settings) *Git {
	return &Git{
		path:     path,
		settings: settings,
	}
}

func (g *Git) IsAvailable() bool {
	// check if repoPath is a git repository
	if _, err := git.PlainOpen(g.path); err != nil {
		fmt.Println("Error opening repository:", err)
		return false
	}
	return true
}

// func (g *Git) hasSubmodules(dir string) bool {
// 	// check if there are submodules
// 	command := []string{"git", "submodule", "status"}
// 	output, err := runCommandWithOutput(command, dir)
// 	if err != nil {
// 		fmt.Println("Error checking submodules:", err)
// 		return false
// 	}
// 	return len(output) > 0
// }

func (g *Git) LatestCommit(ref string) (string, error) {
	// get latest commit
	command := []string{"git", "rev-parse", ref}
	output, err := runCommandWithOutput(command, g.path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

func (g *Git) SavePatch(ref, output string) error {
	// get diff of current working tree vs uncommitted changes
	command := []string{"git", "diff", ref, "--submodule=diff"}
	err := runCommand(command, g.path, output)
	if err != nil {
		return err
	}
	return nil
}

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

func (g *Git) GetDiff() []string {
	filesDirPath := g.settings.GetFilesDir().GetValue()

	diffFiles := []string{}

	// get diff of current working tree vs uncommitted changes
	file := filepath.Join(filesDirPath, diffFileName)
	if err := g.SavePatch("HEAD", file); err != nil {
		fmt.Println("Error generating diff:", err)
	} else {
		diffFiles = append(diffFiles, file)
	}

	// get diff of current working tree vs last commit on upstream branch
	output, err := g.LatestCommit("@{u}")
	if err != nil {
		fmt.Println("Error getting latest commit:", err)
		return diffFiles
	}
	file = filepath.Join(filesDirPath, fmt.Sprintf("diff_%s.patch", output))
	if err := g.SavePatch("@{u}", file); err != nil {
		fmt.Println("Error generating diff:", err)
	} else {
		diffFiles = append(diffFiles, file)
	}
	return diffFiles
}
