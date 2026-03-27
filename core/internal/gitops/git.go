package gitops

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"

	git "github.com/go-git/go-git/v5"

	"github.com/wandb/wandb/core/internal/observability"
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
		defer func() {
			_ = f.Close()
		}()
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

func New(path string, logger *observability.CoreLogger) *Git {
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

// GetLatestUpstreamCommit returns a commit hash representing the upstream
// reference point for the current branch.
//
// If disableGitForkPoint is false,
// it returns the commit where the current branch diverged from upstream.
// Otherwise, it returns the latest commit on the current branch's upstream tracking branch.
func (g *Git) GetLatestUpstreamCommit(disableGitForkPoint bool) (string, error) {
	if !disableGitForkPoint {
		return g.GetUpstreamForkPoint()
	}

	return g.LatestCommit("@{upstream}")
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

// GetUpstreamForkPoint returns the commit hash where the current branch
// diverged from its upstream tracking branch.
//
// If the current branch has a configured tracking branch,
// it returns the merge base with that branch.
// Otherwise, it falls back to finding the most recent common ancestor of HEAD
// across all tracking branches of every local branch.
//
// Returns an empty string if the repository is in a detached
// HEAD state or if no tracking branches are found.
func (g *Git) GetUpstreamForkPoint() (string, error) {
	// check if we're in a detached head state
	isDetached, err := g.isDetachedHead()
	if err != nil {
		return "", err
	}
	if isDetached {
		g.logger.Debug("git is in a detached head state, cannot get fork point")
		return "", nil
	}

	// if there is a tracking branch, then use that as the fork point
	trackingBranch, err := g.getCurrentBranchTrackingBranch()
	if err == nil && trackingBranch != "" {
		return g.findMostRecentAncestor([]string{trackingBranch})
	}

	// if there is no tracking branch,
	// then find the most recent ancestor of HEAD that occurs on an upstream branch
	trackingBranches, err := g.getAllTrackingBranches()
	if err != nil {
		return "", err
	}
	return g.findMostRecentAncestor(trackingBranches)
}

// isDetachedHead checks if the repository is in a detached head state.
func (g *Git) isDetachedHead() (bool, error) {
	_, err := runCommandWithOutput([]string{"git", "symbolic-ref", "HEAD"}, g.path)
	if err != nil {
		if _, ok := errors.AsType[*exec.ExitError](err); ok {
			return true, nil
		}

		return false, err
	}
	return false, nil
}

// getCurrentBranchTrackingBranch returns the tracking branch of the current branch
func (g *Git) getCurrentBranchTrackingBranch() (string, error) {
	output, err := runCommandWithOutput(
		[]string{"git", "rev-parse", "--abbrev-ref", "@{upstream}"},
		g.path,
	)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// getAllTrackingBranches returns tracking branches for all local branches
func (g *Git) getAllTrackingBranches() ([]string, error) {
	output, err := runCommandWithOutput(
		[]string{
			"git",
			"for-each-ref",
			"--format=%(upstream:short)",
			"refs/heads/",
		},
		g.path,
	)
	if err != nil {
		return nil, err
	}

	trackingBranches := make(map[string]struct{})
	for branch := range strings.SplitSeq(string(output), "\n") {
		if branch != "" {
			trackingBranches[branch] = struct{}{}
		}
	}

	trackingBranchesList := make([]string, 0, len(trackingBranches))
	for branch := range trackingBranches {
		trackingBranchesList = append(trackingBranchesList, branch)
	}
	return trackingBranchesList, nil
}

// findMostRecentAncestor finds the most recent common ancestor among provided branches
func (g *Git) findMostRecentAncestor(branches []string) (string, error) {
	if len(branches) == 0 {
		return "", nil
	}

	args := append([]string{"git", "merge-base", "HEAD"}, branches...)
	output, err := runCommandWithOutput(args, g.path)
	if err != nil {
		return "", err
	}

	return strings.TrimSpace(string(output)), nil
}
