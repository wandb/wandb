package gitops

import (
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

func (g *Git) GetLatestUpstreamCommit(findForkPoint bool) (string, error) {
	if findForkPoint {
		return g.GetUpstreamForkPoint()
	}

	return g.LatestCommit("@{u}")
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

func (g *Git) GetUpstreamForkPoint() (string, error) {
	// Check if we're in a detached head state
	if isDetached, err := g.isDetachedHead(); err != nil {
		return "", err
	} else if isDetached {
		g.logger.Debug("git is in a detached head state cannot get fork point")
		return "", nil
	}

	// if there is a tracking branch, then use that as the fork point.
	trackingBranch, err := g.getCurrentBranchTrackingBranch()
	if err == nil && trackingBranch != "" {
		return g.findMostRecentAncestor([]string{trackingBranch})
	}

	// if there is no tracking branch,
	// then find the most recent ancestor of HEAD that occurs on an upstream branch.
	trackingBranches, err := g.getAllTrackingBranches()
	if err != nil {
		return "", err
	}
	return g.findMostRecentAncestor(trackingBranches)
}

// isDetachedHead checks if the repository is in a detached head state
func (g *Git) isDetachedHead() (bool, error) {
	_, err := runCommandWithOutput([]string{"git", "symbolic-ref", "HEAD"}, g.path)
	if err != nil {
		// symbolic-ref fails in detached head state
		return true, nil
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
	branchesOutput, err := runCommandWithOutput(
		[]string{"git", "branch", "--format=%(refname:short)"},
		g.path,
	)
	if err != nil {
		return nil, err
	}

	var trackingBranches []string
	branches := strings.Split(strings.TrimSpace(string(branchesOutput)), "\n")
	for _, branch := range branches {
		branch = strings.TrimSpace(branch)
		if branch == "" {
			continue
		}

		trackingOutput, err := runCommandWithOutput(
			[]string{"git", "rev-parse", "--abbrev-ref", branch + "@{upstream}"},
			g.path,
		)
		if err == nil {
			if trackingBranch := strings.TrimSpace(string(trackingOutput)); trackingBranch != "" {
				trackingBranches = append(trackingBranches, trackingBranch)
			}
		}
	}

	return trackingBranches, nil
}

// findMostRecentAncestor finds the most recent common ancestor among provided branches
func (g *Git) findMostRecentAncestor(branches []string) (string, error) {
	if len(branches) == 0 {
		return "", nil
	}

	var mostRecentAncestor string

	for _, branch := range branches {
		ancestor, err := g.getMergeBase("HEAD", branch)
		if err != nil || ancestor == "" {
			continue
		}

		if mostRecentAncestor == "" {
			mostRecentAncestor = ancestor
		} else if isAncestor, err := g.isAncestor(mostRecentAncestor, ancestor); err == nil && isAncestor {
			mostRecentAncestor = ancestor
		}
	}

	return mostRecentAncestor, nil
}

// getMergeBase returns the merge base between two commits
func (g *Git) getMergeBase(commit1, commit2 string) (string, error) {
	output, err := runCommandWithOutput(
		[]string{"git", "merge-base", commit1, commit2},
		g.path,
	)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// isAncestor checks if commit1 is an ancestor of commit2
func (g *Git) isAncestor(commit1, commit2 string) (bool, error) {
	_, err := runCommandWithOutput(
		[]string{"git", "merge-base", "--is-ancestor", commit1, commit2},
		g.path,
	)
	return err == nil, nil
}
