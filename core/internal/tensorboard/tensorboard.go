// Package tensorboard integrates wandb with TensorBoard.
//
// TensorBoard is a visualization tool, like W&B, that's built for use with
// TensorFlow. https://www.tensorflow.org/tensorboard. This integration
// allows users to view their TensorBoard charts in their W&B runs.
//
// This integration works by reading the "tfevents" files logged by
// TensorBoard and turning them into W&B history updates (i.e. run.log()).
// The exact format of the files is on GitHub and unlikely to change:
// each file is simply a list of Event protos. We are interested in
// Summary events, which contain labeled data that we want to display
// in W&B.
package tensorboard

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
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
	settings      *settings.Settings
	hostname      string
	fileReadDelay waiting.Delay

	// streams is the list of event streams for all tracked directories.
	streams []*tfEventStream

	// rootDir is the inferred "root" directory for TB logs.
	//
	// The Python side of this integration creates TBRecords when
	// TensorBoard starts to write to a new directory. TensorBoard internally
	// creates this directory by joining a namespace like "train" or
	// "validation" to a root path, and we would like to use the namespace
	// as a prefix for logged metrics, like "train/epoch_loss" vs
	// "validation/epoch_loss".
	//
	// The namespace itself may include slashes, so we cannot break apart
	// a log directory into a (root, namespace) pair until we are tracking
	// at least two directories.
	rootDir     *paths.AbsolutePath
	rootDirCond *sync.Cond
	trackedDirs []paths.AbsolutePath
}

type Params struct {
	OutputRecords chan<- *service.Record

	Logger   *observability.CoreLogger
	Settings *settings.Settings

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

		rootDirCond: sync.NewCond(&sync.Mutex{}),
		trackedDirs: make([]paths.AbsolutePath, 0),
	}

	return tb
}

// Handle begins processing the events in a TensorBoard logs directory.
func (tb *TBHandler) Handle(record *service.TBRecord) error {
	shouldSave := record.Save

	maybeLogDir, err := paths.Absolute(record.LogDir)
	if err != nil {
		return fmt.Errorf(
			"tensorboard: cannot make logDir %v absolute: %v",
			record.LogDir,
			err)
	}
	logDir := *maybeLogDir

	if err := tb.updateRootDirFromLogDir(logDir); err != nil {
		return fmt.Errorf("tensorboard: failed when updating root dir: %v", err)
	}

	var maybeRootDir *paths.AbsolutePath
	if record.GetRootDir() != "" {
		var err error
		maybeRootDir, err = paths.Absolute(record.GetRootDir())
		if err != nil {
			return fmt.Errorf(
				"tensorboard: cannot make rootDir %v absolute: %v",
				record.GetRootDir(),
				err)
		}
	}

	stream := NewTFEventStream(
		logDir,
		tb.fileReadDelay,
		TFEventsFileFilter{
			StartTimeSec: tb.settings.GetStartTime().Unix(),
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

		var rootDir paths.AbsolutePath
		if maybeRootDir != nil {
			rootDir = *maybeRootDir
		} else {
			rootDir = tb.waitForRootDir()
		}

		tb.convertToRunHistory(
			stream.Events(),
			tb.getNamespace(logDir, rootDir),
		)
	}()

	tb.wg.Add(1)
	go func() {
		defer tb.wg.Done()

		var rootDir paths.AbsolutePath
		if maybeRootDir != nil {
			rootDir = *maybeRootDir
		} else {
			rootDir = tb.waitForRootDir()
		}

		tb.saveFiles(stream.Files(), shouldSave, rootDir)
	}()

	stream.Start()
	return nil
}

func (tb *TBHandler) Finish() {
	for _, stream := range tb.streams {
		stream.Stop()
	}

	tb.wg.Wait()
}

// updateRootDirFromLogDir updates the inferred rootDir.
func (tb *TBHandler) updateRootDirFromLogDir(
	newLogDir paths.AbsolutePath,
) error {
	tb.rootDirCond.L.Lock()
	defer tb.rootDirCond.L.Unlock()

	tb.trackedDirs = append(tb.trackedDirs, newLogDir)

	if len(tb.trackedDirs) > 1 {
		longestPrefix := string(tb.trackedDirs[0])

		for _, path := range tb.trackedDirs[1:] {
			pathRunes := []rune(string(path))

			for i, char := range longestPrefix {
				if char != pathRunes[i] {
					longestPrefix = longestPrefix[:i]
					break
				}
			}
		}

		rootDir, err := paths.Absolute(longestPrefix)
		if err != nil {
			return err
		}

		tb.rootDir = rootDir
		tb.rootDirCond.Broadcast()
	}

	return nil
}

// waitForRootDir blocks until rootDir is set.
func (tb *TBHandler) waitForRootDir() paths.AbsolutePath {
	tb.rootDirCond.L.Lock()
	defer tb.rootDirCond.L.Unlock()

	// TODO: What if we're stuck here and need to finish?
	for tb.rootDir == nil {
		tb.rootDirCond.Wait()
	}

	return *tb.rootDir
}

func (tb *TBHandler) convertToRunHistory(
	events <-chan *tbproto.TFEvent,
	namespace string,
) {
	converter := TFEventConverter{Namespace: namespace}

	for event := range events {
		tb.logger.Debug(
			"tensorboard: processed event",
			"event", event,
			"namespace", namespace,
		)

		if history := converter.Convert(event, tb.logger); history != nil {
			tb.sendHistoryRecord(history)
		}
	}
}

func (tb *TBHandler) sendHistoryRecord(history *service.HistoryRecord) {
	tb.outChan <- &service.Record{
		RecordType: &service.Record_History{
			History: history,
		},

		// Don't persist the record to the transaction log---
		// the data already exists in tfevents files.
		Control: &service.Control{Local: true},
	}
}

func (tb *TBHandler) saveFiles(
	files <-chan paths.AbsolutePath,
	shouldSave bool,
	rootDir paths.AbsolutePath,
) {
	for file := range files {
		if shouldSave {
			tb.saveFile(file, rootDir)
		}
	}
}

// saveFile saves a TensorBoard file with the run.
//
// This does just two things:
//  1. Symlinks the file into the run's directory.
//  2. Saves a record to upload the file at the end of the run.
//
// The `rootDir` must be an ancestor of `path`. The file's upload path is
// determined by its path relative to the `rootDir`.
func (tb *TBHandler) saveFile(path, rootDir paths.AbsolutePath) {
	tb.logger.Debug(
		"tensorboard: saving file",
		"path", path,
		"rootDir", rootDir,
	)

	maybeRelPath, err := path.RelativeTo(rootDir)
	if err != nil {
		tb.logger.CaptureError(
			"tensorboard: error getting relative path", err,
			"rootDir", rootDir,
			"path", path)
		return
	}
	relPath := *maybeRelPath

	if !relPath.IsLocal() {
		tb.logger.CaptureError(
			"tensorboard: file is not under TB root", nil,
			"rootDir", rootDir,
			"path", path,
		)
		return
	}

	// Symlink the file.
	targetPath := filepath.Join(tb.settings.GetFilesDir(), string(relPath))
	if err := os.MkdirAll(filepath.Dir(targetPath), os.ModePerm); err != nil {
		tb.logger.Error("tensorboard: error creating directory",
			"directory", filepath.Dir(targetPath),
			"error", err)
		return
	}
	if err := os.Symlink(string(path), targetPath); err != nil {
		tb.logger.Error("tensorboard: error creating symlink",
			"target", path,
			"symlink", targetPath,
			"error", err)
		return
	}

	// Write a record indicating that the file should be uploaded.
	tb.outChan <- &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{Policy: service.FilesItem_END, Path: string(relPath)},
				},
			},
		},
	}
}

// getNamespace computes the namespace corresponding to a log directory.
//
// The namespace is used as a prefix for logged metrics in W&B.
func (tb *TBHandler) getNamespace(logDir, rootDir paths.AbsolutePath) string {
	namespace, success := strings.CutPrefix(string(logDir), string(rootDir))

	if !success {
		tb.logger.CaptureError(
			"tensorboard: rootDir not prefix of logDir",
			nil,
			"rootDir", rootDir,
			"logDir", logDir,
		)
		return ""
	}

	return strings.Trim(
		strings.ReplaceAll(
			namespace,
			string(filepath.Separator),
			"/"),
		"/",
	)
}
