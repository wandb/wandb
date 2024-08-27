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
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TBHandler saves TensorBoard data with the run.
type TBHandler struct {
	mu sync.Mutex

	// startWG is done after all streams are started.
	//
	// This is used to ensure that all tfevents are read even if
	// Finish() is called immediately after Handle().
	startWG sync.WaitGroup

	// wg is done after all work is done.
	wg sync.WaitGroup

	extraWork     runwork.ExtraWork
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
	runwork.ExtraWork

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
		extraWork:     params.ExtraWork,
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
func (tb *TBHandler) Handle(record *spb.TBRecord) error {
	// Make log_dir absolute.
	maybeLogDir, err := paths.Absolute(record.LogDir)
	if err != nil {
		return fmt.Errorf(
			"tensorboard: cannot make logDir %v absolute: %v",
			record.LogDir,
			err)
	}
	logDir := *maybeLogDir

	// Make root_dir absolute, if set.
	var explicitRootDir *paths.AbsolutePath
	if record.GetRootDir() != "" {
		var err error
		explicitRootDir, err = paths.Absolute(record.GetRootDir())
		if err != nil {
			return fmt.Errorf(
				"tensorboard: cannot make rootDir %v absolute: %v",
				record.GetRootDir(),
				err)
		}
	}

	// Update the inferred root directory.
	if err := tb.updateRootDirFromLogDir(logDir); err != nil {
		return err
	}

	// Create the event stream.
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

	tb.startStream(stream, logDir, explicitRootDir, record.Save)

	return nil
}

// startStream starts to process tfevents files.
//
// The stream should not already be started.
func (tb *TBHandler) startStream(
	stream *tfEventStream,
	logDir paths.AbsolutePath,
	explicitRootDir *paths.AbsolutePath,
	shouldSave bool,
) {
	tb.wg.Add(1)
	tb.startWG.Add(1)
	go func() {
		defer tb.wg.Done()

		// We may have to wait a short time for the root directory if
		// it is not set explicitly.
		var rootDir paths.AbsolutePath
		if explicitRootDir != nil {
			rootDir = *explicitRootDir
		} else {
			inferredRootDir, err := tb.inferRootDir()

			if err != nil {
				tb.logger.CaptureError(
					fmt.Errorf(
						"tensorboard: failed to infer root directory: %v",
						err,
					))
				tb.startWG.Done()
				return
			}

			rootDir = *inferredRootDir
		}

		stream.Start()
		tb.startWG.Done()

		tb.watch(
			stream,
			tb.getNamespace(logDir, rootDir),
			rootDir,
			shouldSave,
		)
	}()
}

// watch consumes the TF event stream, uploading tfevents files
// and logging events to the run.
func (tb *TBHandler) watch(
	stream *tfEventStream,
	namespace string,
	rootDir paths.AbsolutePath,
	save bool,
) {
	wg := &sync.WaitGroup{}

	wg.Add(1)
	go func() {
		defer wg.Done()
		tb.convertToRunHistory(stream.Events(), namespace)
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		tb.saveFiles(stream.Files(), save, rootDir)
	}()

	wg.Wait()
}

func (tb *TBHandler) Finish() {
	tb.startWG.Wait()

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
			return fmt.Errorf(
				"tensorboard: error while inferring root dir: %v",
				err,
			)
		}

		tb.rootDir = rootDir
		tb.rootDirCond.Broadcast()
	}

	return nil
}

// inferRootDir blocks until rootDir is set.
//
// After a timeout, this just returns the current working directory.
func (tb *TBHandler) inferRootDir() (*paths.AbsolutePath, error) {
	resultChan := make(chan paths.AbsolutePath, 1)
	go func() {
		tb.rootDirCond.L.Lock()
		defer tb.rootDirCond.L.Unlock()

		for tb.rootDir == nil {
			tb.rootDirCond.Wait()
		}

		resultChan <- *tb.rootDir
	}()

	// The root directory can be inferred after at least two log directories
	// are identified. Often this is a "train" and a "validate" directory.
	//
	// We get those directories by spying on TensorBoard internals via
	// monkeypatching in Python (!?), so we don't control it and don't
	// know whether it will or will not emit more than one. If it doesn't,
	// then we just default to the current working directory as a root.
	select {
	case result := <-resultChan:
		return &result, nil
	case <-time.After(10 * time.Second):
		return paths.CWD()
	}
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

		emitter := NewTFEmitter(tb.settings)
		converter.ConvertNext(emitter, event, tb.logger)
		emitter.Emit(tb.extraWork)
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
			fmt.Errorf("tensorboard: error getting relative path: %v", err),
			"rootDir", rootDir,
			"path", path)
		return
	}
	relPath := *maybeRelPath

	if !relPath.IsLocal() {
		tb.logger.CaptureError(
			errors.New("tensorboard: file is not under TB root"),
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
	tb.extraWork.AddRecord(
		&spb.Record{
			RecordType: &spb.Record_Files{
				Files: &spb.FilesRecord{
					Files: []*spb.FilesItem{
						{Policy: spb.FilesItem_END, Path: string(relPath)},
					},
				},
			},
		})
}

// getNamespace computes the namespace corresponding to a log directory.
//
// The namespace is used as a prefix for logged metrics in W&B.
func (tb *TBHandler) getNamespace(logDir, rootDir paths.AbsolutePath) string {
	namespace, success := strings.CutPrefix(string(logDir), string(rootDir))

	if !success {
		tb.logger.CaptureError(
			errors.New("tensorboard: rootDir not prefix of logDir"),
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
