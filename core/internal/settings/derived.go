package settings

import (
	"path/filepath"

	"github.com/google/wire"
)

// This file contains settings that can affect how a run is logged.
//
// Since settings are not stored in the transaction log, we must be able to
// re-derive these when syncing.
//
// Arguably, these should not be settings at all. This file creates types
// to make it easier to pass these values as constructor parameters to
// components that rely on them. All types should be passed by value.

// DerivedSettingsProviders provides all derived settings.
var DerivedSettingsProviders = wire.NewSet(InferFilesDir)

// SyncDir is the path to the run's sync directory.
//
// For example, ".../run-20250913-123456-abcdefgh/".
type SyncDir string

// FilesDir is where a run's files are stored, including the user's files
// saved with `run.save()` in Python and generated files like `output.log`.
type FilesDir string

func InferFilesDir(syncDir SyncDir) FilesDir {
	// Must match the logic of wandb.Settings.files_dir
	return FilesDir(filepath.Join(string(syncDir), "files"))
}
