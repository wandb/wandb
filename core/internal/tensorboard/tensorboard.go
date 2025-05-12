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
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/waiting"

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

	rootDirGuesser *RootDirGuesser
	extraWork      runwork.ExtraWork
	logger         *observability.CoreLogger
	settings       *settings.Settings
	fileReadDelay  waiting.Delay

	// streams is the list of event streams for all tracked directories.
	streams []*tfEventStream
}

type Params struct {
	runwork.ExtraWork

	Logger   *observability.CoreLogger
	Settings *settings.Settings

	FileReadDelay waiting.Delay
}

func NewTBHandler(params Params) *TBHandler {
	if params.FileReadDelay == nil {
		params.FileReadDelay = waiting.NewDelay(5 * time.Second)
	}

	tb := &TBHandler{
		rootDirGuesser: NewRootDirGuesser(params.Logger),
		extraWork:      params.ExtraWork,
		logger:         params.Logger,
		settings:       params.Settings,
		fileReadDelay:  params.FileReadDelay,

		streams: make([]*tfEventStream, 0),
	}

	return tb
}

// Handle begins processing the events in a TensorBoard logs directory.
func (tb *TBHandler) Handle(record *spb.TBRecord) error {
	logDir, err := ParseTBPath(record.LogDir)
	if err != nil {
		return fmt.Errorf("tensorboard: failed to parse path: %v", err)
	}

	tb.rootDirGuesser.AddLogDirectory(logDir)

	stream := NewTFEventStream(
		tb.extraWork.BeforeEndCtx(),
		logDir,
		tb.fileReadDelay,
		TFEventsFileFilter{
			StartTimeSec: tb.settings.GetStartTime().Unix(),
			Hostname:     tb.settings.GetHostname(),
		},
		tb.logger,
	)

	tb.mu.Lock()
	tb.streams = append(tb.streams, stream)
	tb.mu.Unlock()

	var explicitRootDir *RootDir

	if record.RootDir != "" {
		explicitRootDir = NewRootDir(record.RootDir)
	}

	tb.startStream(stream, logDir, explicitRootDir, record.Save)

	return nil
}

// startStream starts to process tfevents files.
//
// The stream should not already be started.
func (tb *TBHandler) startStream(
	stream *tfEventStream,
	logDir *LocalOrCloudPath,
	explicitRootDir *RootDir,
	shouldSave bool,
) {
	tb.wg.Add(1)
	tb.startWG.Add(1)
	go func() {
		defer tb.wg.Done()

		rootDir := explicitRootDir

		// If the root wasn't given explicitly, try to guess it.
		if rootDir == nil {
			rootDir = tb.rootDirGuesser.InferRootOrTimeout(
				logDir,
				10*time.Second,
			)

		}

		// If we couldn't guess it and tfevents files are on the local
		// filesystem, try to use the current working directory.
		if rootDir == nil && logDir.LocalPath != nil {
			var err error
			rootDir, err = RootDirFromCWD()

			if err != nil {
				tb.logger.Warn(
					"tensorboard: failed to use current working directory"+
						" as the root directory",
					"error", err)
			}
		}

		namespace, err := rootDir.TrimFrom(logDir)

		if err != nil {
			namespace = logDir.Base()
			tb.logger.Warn(
				"tensorboard: failed to compute namespace, using default",
				"error", err,
				"default", namespace)
		}

		tb.logger.Info(
			"tensorboard: tracking new log directory",
			"rootDir", rootDir,
			"logDir", logDir,
			"namespace", namespace)

		stream.Start()
		tb.startWG.Done()

		tb.watch(stream, namespace, rootDir, shouldSave)
	}()
}

// watch consumes the TF event stream, uploading tfevents files
// and logging events to the run.
func (tb *TBHandler) watch(
	stream *tfEventStream,
	namespace string,
	rootDir *RootDir,
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
	files <-chan *LocalOrCloudPath,
	shouldSave bool,
	rootDir *RootDir,
) {
	for file := range files {
		if !shouldSave {
			continue
		}

		if file.LocalPath == nil {
			tb.logger.Warn(
				"tensorboard: not saving tfevents file because it is in"+
					" the cloud",
				"file", file.CloudPath)
			continue
		}
		localPath := *file.LocalPath

		runPath, err := rootDir.TrimFrom(file)

		if err != nil {
			tb.logger.Error(
				"tensorboard: failed to infer path where to save file",
				"file", localPath,
				"error", err,
			)
			continue
		}

		tb.saveFile(localPath, runPath)
	}
}

// saveFile saves a TensorBoard file with the run.
//
// This does just two things:
//  1. Symlinks the file into the run's directory.
//  2. Saves a record to upload the file at the end of the run.
//
// The file's path in the run's files directory is given by runPath.
func (tb *TBHandler) saveFile(
	fileLocation paths.AbsolutePath,
	runPath string,
) {
	tb.logger.Info(
		"tensorboard: saving file",
		"fileLocation", fileLocation,
		"runPath", runPath,
	)

	if !filepath.IsLocal(runPath) {
		tb.logger.Error(
			"tensorboard: invalid run file path",
			"runPath", runPath)
		return
	}

	// Symlink the file.
	targetPath := filepath.Join(tb.settings.GetFilesDir(), runPath)
	if err := os.MkdirAll(filepath.Dir(targetPath), os.ModePerm); err != nil {
		tb.logger.Error("tensorboard: error creating directory",
			"directory", filepath.Dir(targetPath),
			"error", err)
		return
	}
	if err := os.Symlink(string(fileLocation), targetPath); err != nil {
		tb.logger.Error("tensorboard: error creating symlink",
			"target", fileLocation,
			"symlink", targetPath,
			"error", err)
		return
	}

	// Write a record indicating that the file should be uploaded.
	tb.extraWork.AddWork(
		runwork.WorkFromRecord(
			&spb.Record{
				RecordType: &spb.Record_Files{
					Files: &spb.FilesRecord{
						Files: []*spb.FilesItem{
							{Policy: spb.FilesItem_END, Path: runPath},
						},
					},
				},
			}))
}
