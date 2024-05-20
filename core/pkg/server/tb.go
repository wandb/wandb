package server

import (
	"io/fs"
	"os"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// TBHandler saves Tensorboard event logs as run files.
type TBHandler struct {
	mu sync.Mutex

	watcher    watcher.Watcher
	workingDir string
	tracked    map[string]struct{}
	logger     *observability.CoreLogger
	settings   *service.Settings
	outChan    chan *service.Record
}

func NewTBHandler(
	watcher watcher.Watcher,
	logger *observability.CoreLogger,
	settings *service.Settings,
	outChan chan *service.Record,
) *TBHandler {
	tb := &TBHandler{
		watcher:  watcher,
		tracked:  make(map[string]struct{}),
		outChan:  outChan,
		logger:   logger,
		settings: settings,
	}
	workingDir, err := os.Getwd()
	if err != nil {
		logger.CaptureError("error getting working directory", err)
	}
	tb.workingDir = workingDir
	return tb
}

// Handle begins watching the specified Tensorboard logs directory.
func (tb *TBHandler) Handle(record *service.TBRecord) error {
	if err := tb.watcher.WatchTree(
		record.GetLogDir(),
		tb.saveFile,
	); err != nil {
		return err
	}

	return tb.saveDirectory(record.GetLogDir())
}

// saveDirectory recursively saves all Tensorboard files in the directory.
func (tb *TBHandler) saveDirectory(path string) error {
	return filepath.WalkDir(path,
		func(path string, d fs.DirEntry, err error) error {
			// Skip any errors we encounter.
			if err != nil {
				return nil
			}

			// Save files.
			if !d.IsDir() {
				tb.saveFile(path)
			}

			return nil
		})
}

// saveFile saves a Tensorboard file with the run.
//
// This does just two things:
//  1. Symlinks the file into the run's directory.
//  2. Saves a record to upload the file at the end of the run.
func (tb *TBHandler) saveFile(path string) {
	tb.logger.Debug("tensorboard: update", "path", path)

	// Skip directories and files that don't exist.
	if fileInfo, err := os.Stat(path); err != nil || fileInfo.IsDir() {
		tb.logger.Warn(
			"tensorboard: skipping because failed to stat, or the path is a directory",
			"error", err,
			"path", path)
		return
	}

	// Get the absolute and relative versions of the path.
	absolutePath, err := filepath.Abs(path)
	if err != nil {
		tb.logger.CaptureError(
			"tensorboard: error getting absolute path", err,
			"path", path)
		return
	}
	relativePath, err := filepath.Rel(tb.workingDir, absolutePath)
	if err != nil {
		tb.logger.CaptureError(
			"tensorboard: error getting relative path", err,
			"workingDir", tb.workingDir,
			"path", absolutePath)
		return
	}

	// Skip if we're already tracking the file.
	tb.mu.Lock()
	if _, ok := tb.tracked[relativePath]; ok {
		tb.mu.Unlock()
		return
	}
	tb.tracked[relativePath] = struct{}{}
	tb.mu.Unlock()

	// Symlink the file.
	targetPath := filepath.Join(tb.settings.GetFilesDir().GetValue(), relativePath)
	if err := os.MkdirAll(filepath.Dir(targetPath), os.ModePerm); err != nil {
		tb.logger.Error("tensorboard: error creating directory",
			"directory", filepath.Dir(targetPath),
			"error", err)
		return
	}
	if err := os.Symlink(absolutePath, targetPath); err != nil {
		tb.logger.Error("tensorboard: error creating symlink",
			"target", absolutePath,
			"symlink", targetPath,
			"error", err)
		return
	}

	// Write a record indicating that the file should be uploaded.
	tb.outChan <- &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{Policy: service.FilesItem_END, Path: relativePath},
				},
			},
		},
	}
}
