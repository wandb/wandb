package server

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"

	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// TBHandler saves TensorBoard data with the run.
type TBHandler struct {
	mu sync.Mutex

	watcher    watcher.Watcher
	workingDir string
	tracked    map[string]struct{}
	logger     *observability.CoreLogger
	settings   *service.Settings
	outChan    chan *service.Record
	hostname   string
}

func NewTBHandler(
	watcher watcher.Watcher,
	logger *observability.CoreLogger,
	settings *service.Settings,
	outChan chan *service.Record,
	hostname string,
) *TBHandler {
	tb := &TBHandler{
		watcher:  watcher,
		tracked:  make(map[string]struct{}),
		outChan:  outChan,
		logger:   logger,
		settings: settings,
		hostname: hostname,
	}
	workingDir, err := os.Getwd()
	if err != nil {
		logger.CaptureError("error getting working directory", err)
	}
	tb.workingDir = workingDir
	return tb
}

// Handle begins watching the specified TensorBoard logs directory.
func (tb *TBHandler) Handle(record *service.TBRecord) error {
	if !record.Save {
		return nil
	}

	rootDir := record.GetRootDir()
	if !filepath.IsAbs(rootDir) {
		var err error
		rootDir, err = filepath.Abs(filepath.Join(tb.workingDir, rootDir))
		if err != nil {
			return err
		}
	}

	if err := tb.watcher.WatchTree(
		record.GetLogDir(),
		func(path string) { tb.saveFile(path, rootDir) },
	); err != nil {
		return err
	}

	return tb.saveDirectory(record.GetLogDir(), rootDir)
}

// saveDirectory recursively saves all TensorBoard files in the directory.
func (tb *TBHandler) saveDirectory(path string, rootDir string) error {
	return filepath.WalkDir(path,
		func(path string, d fs.DirEntry, err error) error {
			// Skip any errors we encounter.
			if err != nil {
				return nil
			}

			// Save files.
			if !d.IsDir() {
				tb.saveFile(path, rootDir)
			}

			return nil
		})
}

// saveFile saves a TensorBoard file with the run.
//
// This does just two things:
//  1. Symlinks the file into the run's directory.
//  2. Saves a record to upload the file at the end of the run.
//
// The `rootDir` must an absolute path that is an ancestor of `path`.
// It is used to compute the filename to use when saving the file to the run.
func (tb *TBHandler) saveFile(path string, rootDir string) {
	tb.logger.Debug(
		"tensorboard: update",
		"path", path,
		"rootDir", rootDir,
	)

	if !tb.isTfeventsForThisRun(path) {
		return
	}

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
	relativePath, err := filepath.Rel(rootDir, absolutePath)
	if err != nil {
		tb.logger.CaptureError(
			"tensorboard: error getting relative path", err,
			"rootDir", rootDir,
			"path", absolutePath)
		return
	}

	if !filepath.IsLocal(relativePath) {
		tb.logger.CaptureError(
			"tensorboard: file is not under TB root", nil,
			"rootDir", rootDir,
			"path", absolutePath,
		)
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

// isTfeventsForThisRun reports whether the given path refers to a tfevents
// file that belongs to the current run.
//
// This is a heuristic that relies on TensorBoard internals and interactions
// with other known tools.
func (tb *TBHandler) isTfeventsForThisRun(path string) bool {
	name := filepath.Base(path)

	switch {
	// The TensorFlow profiler creates an empty tfevents file with this suffix.
	case strings.HasSuffix(name, ".profile-empty"):
		return false

	// Amazon SageMaker creates temporary tfevents files with the suffix
	// .sagemaker-uploaded which we don't want to upload.
	case strings.HasSuffix(name, ".sagemaker-uploaded"):
		return false
	}

	// We expect a filename containing
	//    tfevents.<time>.<hostname>
	//
	// TensorBoard format: https://github.com/tensorflow/tensorboard/blob/f3f26b46981da5bd46a5bb93fcf02d9eb7608bc1/tensorboard/summary/writer/event_file_writer.py#L81
	// TensorFlow format: https://github.com/tensorflow/tensorflow/blob/8f597046dc30c14b5413813d02c0e0aed399c177/tensorflow/core/util/events_writer.cc#L68
	//
	// The <time> is a time in seconds that's related to when the events file
	// was created---a TensorBoard logs directory can accumulate files each
	// time the user runs their script, and we don't want to associate files
	// from before the run with this run.
	//
	// The <hostname> is exactly as reported through HOSTNAME(1) on the machine
	// writing the file. A logs directory may be in the cloud or on some remote
	// filesystem and written to by multiple machines. Only files created on our
	// same machine are relevant to the run.
	//
	// As one might expect, these heuristics aren't perfect. For example, a user
	// might run multiple TB processes simultaneously, in which case there will
	// be files with the correct <time> and <hostname> that aren't related to
	// this run. It's also not clear whether <hostname> ever needs to be escaped.
	// And of course this could break with a future version of TB.
	re, err := regexp.Compile(
		fmt.Sprintf(
			`tfevents\.(\d+)\.%v`,
			regexp.QuoteMeta(tb.hostname),
		),
	)
	if err != nil {
		panic(err)
	}

	matches := re.FindStringSubmatch(name)
	if matches == nil {
		return false
	}

	tfeventsTime, err := strconv.ParseInt(matches[1], 10, 64)
	if err != nil {
		return false
	}

	return tfeventsTime >= int64(tb.settings.XStartTime.GetValue())
}
