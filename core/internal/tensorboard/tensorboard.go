// Package tensorboard integrates wandb with TensorBoard.
//
// TensorBoard is a visualization tool, like W&B, that's built for use with
// TensorFlow. https://www.tensorflow.org/tensorboard. This integration
// allows users to view their TensorBoard charts in their W&B runs.
package tensorboard

import (
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// TBHandler saves TensorBoard data with the run.
type TBHandler struct {
	mu sync.Mutex
	wg sync.WaitGroup

	outChan       chan<- *service.Record
	logger        *observability.CoreLogger
	settings      *service.Settings
	hostname      string
	fileReadDelay waiting.Delay

	workingDir string
	streams    []*tfEventStream
}

type Params struct {
	OutputRecords chan<- *service.Record

	Logger   *observability.CoreLogger
	Settings *service.Settings

	Hostname      string
	FileReadDelay waiting.Delay
}

func NewTBHandler(params Params) *TBHandler {
	if params.FileReadDelay == nil {
		params.FileReadDelay = waiting.NewDelay(5 * time.Second)
	}

	tb := &TBHandler{
		outChan:       params.OutputRecords,
		logger:        params.Logger,
		settings:      params.Settings,
		hostname:      params.Hostname,
		fileReadDelay: params.FileReadDelay,

		streams: make([]*tfEventStream, 0),
	}
	workingDir, err := os.Getwd()
	if err != nil {
		params.Logger.CaptureError("error getting working directory", err)
	}
	tb.workingDir = workingDir
	return tb
}

// Handle begins processing the events in a TensorBoard logs directory.
func (tb *TBHandler) Handle(record *service.TBRecord) {
	shouldSave := record.Save
	rootDir := record.GetRootDir()
	if !filepath.IsAbs(rootDir) {
		rootDir = filepath.Clean(filepath.Join(tb.workingDir, rootDir))
	}

	stream := NewTFEventStream(
		record.LogDir,
		tb.fileReadDelay,
		TFEventsFileFilter{
			StartTimeSec: int64(tb.settings.XStartTime.GetValue()),
			Hostname:     tb.hostname,
		},
		tb.logger,
	)

	tb.mu.Lock()
	tb.streams = append(tb.streams, stream)
	tb.mu.Unlock()

	tb.wg.Add(1)
	go func() {
		defer tb.wg.Done()
		for event := range stream.Events() {
			tb.logger.Debug("tensorboard: processed event", "event", event)
		}
	}()

	tb.wg.Add(1)
	go func() {
		defer tb.wg.Done()
		for file := range stream.Files() {
			if shouldSave {
				tb.saveFile(file, rootDir)
			}
		}
	}()

	stream.Start()
}

func (tb *TBHandler) Finish() {
	for _, stream := range tb.streams {
		stream.Stop()
	}

	tb.wg.Wait()
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
