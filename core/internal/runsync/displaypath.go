package runsync

import (
	"path/filepath"
	"regexp"
	"strings"
)

// DisplayPath is a shorter form of a transaction log path that's better
// for printing.
//
// Can be formatted with the %s, %q, %v and %#v forms like a normal string.
type DisplayPath string

var runIDFileNameRe = regexp.MustCompile(`run-(.+)\.wandb`)

// ToDisplayPath returns a shortened version of the transactionLogPath
// for showing in user output.
func ToDisplayPath(transactionLogPath, cwd string) DisplayPath {
	maybeSyncDir := maybeGetSyncDir(transactionLogPath)

	result, err := filepath.Rel(cwd, maybeSyncDir)
	if err != nil || len(maybeSyncDir) <= len(result) {
		return DisplayPath(maybeSyncDir)
	}

	return DisplayPath(result)
}

// maybeGetSyncDir returns the sync directory for the .wandb file path if it
// appears to be inside such a directory.
func maybeGetSyncDir(transactionLogPath string) string {
	// Extract the run ID from the file path.
	fileName := filepath.Base(transactionLogPath)
	match := runIDFileNameRe.FindStringSubmatch(fileName)
	if len(match) != 2 {
		return transactionLogPath
	}
	runID := match[1]

	// Check if the parent directory includes the run ID.
	//
	// It's possible (but perhaps shouldn't be) to move a .wandb file to a new
	// directory and sync it. This check makes sure that we don't drop
	// meaningful information from the display name.
	syncDir := filepath.Dir(transactionLogPath)
	syncDirName := filepath.Base(syncDir)

	if !strings.Contains(syncDirName, runID) {
		return transactionLogPath
	}

	return syncDir
}
