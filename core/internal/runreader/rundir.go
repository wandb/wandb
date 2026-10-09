// Package runreader reads a run's data back from the transaction log in its
// local run directory, whether the run is finished or still being written.
package runreader

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"
)

// runDirRe matches "run-YYYYMMDD_HHMMSS-<run_id>" with an optional "offline-"
// prefix and the "-N" suffix the SDK adds when the name is already taken.
var runDirRe = regexp.MustCompile(`^(offline-)?run-(\d{8}_\d{6})-.+$`)

// RunDir is what a run's directory and file names say about the run, which
// is all that is known before its run record is written.
type RunDir struct {
	// WandbFile is the path of the run's transaction log, run-<run_id>.wandb.
	WandbFile string

	// RunID is the run ID in the transaction log's name.
	RunID string

	// Offline is true for runs started in offline mode.
	Offline bool

	// startTime is the local start time in the directory name, for ordering.
	startTime time.Time
}

// ParseRunDir describes the run whose transaction log is at wandbFile.
func ParseRunDir(wandbFile string) RunDir {
	base := filepath.Base(wandbFile)
	dir := RunDir{
		WandbFile: wandbFile,
		RunID:     strings.TrimSuffix(strings.TrimPrefix(base, "run-"), ".wandb"),
	}
	if m := runDirRe.FindStringSubmatch(filepath.Base(filepath.Dir(wandbFile))); m != nil {
		dir.Offline = m[1] != ""
		dir.startTime, _ = time.ParseInLocation("20060102_150405", m[2], time.Local)
	}
	return dir
}

// ListRunDirs returns the runs in a wandb directory, newest first. A run
// directory without exactly one transaction log is skipped.
func ListRunDirs(wandbDir string) ([]RunDir, error) {
	entries, err := os.ReadDir(wandbDir)
	if err != nil {
		return nil, err
	}

	var dirs []RunDir
	for _, entry := range entries {
		if !entry.IsDir() || !runDirRe.MatchString(entry.Name()) {
			continue
		}
		if file := wandbFileIn(filepath.Join(wandbDir, entry.Name())); file != "" {
			dirs = append(dirs, ParseRunDir(file))
		}
	}

	slices.SortFunc(dirs, func(a, b RunDir) int {
		if c := b.startTime.Compare(a.startTime); c != 0 {
			return c
		}
		return strings.Compare(a.WandbFile, b.WandbFile)
	})
	return dirs, nil
}

// wandbFileIn returns the one run-<run_id>.wandb file in a run directory, or
// "" if there is not exactly one.
func wandbFileIn(dir string) string {
	entries, _ := os.ReadDir(dir)
	var file string
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() ||
			!strings.HasPrefix(name, "run-") ||
			!strings.HasSuffix(name, ".wandb") {
			continue
		}
		if file != "" {
			return ""
		}
		file = filepath.Join(dir, name)
	}
	return file
}
