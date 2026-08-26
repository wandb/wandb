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

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TBHandlerProviders binds TBHandlerFactory.
var TBHandlerProviders = wire.NewSet(
	wire.Struct(new(TBHandlerFactory), "*"),
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
	fileReadDelay  time.Duration

	// streams is the list of event streams for all tracked directories.
	streams []*tfEventStream
}

// TBHandlerFactory constructs a TBHandler.
type TBHandlerFactory struct {
	Logger   *observability.CoreLogger
	Settings *settings.Settings
}

func (f *TBHandlerFactory) New(
	extraWork runwork.ExtraWork,
	fileReadDelay time.Duration,
) *TBHandler {
	tb := &TBHandler{
		rootDirGuesser: NewRootDirGuesser(f.Logger),
		extraWork:      extraWork,
		logger:         f.Logger,
		settings:       f.Settings,
		fileReadDelay:  fileReadDelay,

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

	fileFilter := TFEventsFileFilter{}
	if !record.IgnoreTimestamp {
		fileFilter.StartTimeSec = tb.settings.GetStartTime().Unix()
	}
	if !record.IgnoreHostname {
		fileFilter.Hostname = tb.settings.GetHostname()
	}

	stream := NewTFEventStream(
		tb.extraWork.BeforeEndCtx(),
		logDir,
		tb.fileReadDelay,
		fileFilter,
		tb.logger,
	)

	tb.mu.Lock()
	tb.streams = append(tb.streams, stream)
	tb.mu.Unlock()

	var explicitRootDir *RootDir

	if record.RootDir != "" {
		explicitRootDir = NewRootDir(record.RootDir)
	}

	tb.startStream(stream, logDir, explicitRootDir, record)

	return nil
}

// startStream starts to process tfevents files.
//
// The stream should not already be started.
func (tb *TBHandler) startStream(
	stream *tfEventStream,
	logDir *LocalOrCloudPath,
	explicitRootDir *RootDir,
	record *spb.TBRecord,
) {
	tb.wg.Add(1)
	tb.startWG.Add(1)
	go func() {
		defer tb.wg.Done()

		// Lazily compute a RootDir if it is needed.
		lazyRootDirAndNamespace := sync.OnceValues(func() (*RootDir, string) {
			return tb.getRootDirAndNamespace(explicitRootDir, logDir)
		})

		// Figure out the prefix for metric keys.
		var namespace string
		if record.Namespace != nil {
			namespace = *record.Namespace
		} else {
			_, namespace = lazyRootDirAndNamespace()
		}

		// Figure out where to save files, if needed.
		var fileNamer FileNamer
		switch {
		case !record.Save:
			fileNamer = nil
		case record.SavePath != "":
			fileNamer = PrefixFileNamer(record.SavePath)
		default:
			rootDir, _ := lazyRootDirAndNamespace()
			fileNamer = RootDirFileNamer(rootDir)
		}

		tb.logger.Info(
			"tensorboard: tracking new log directory",
			"logDir", logDir,
			"namespace", namespace)

		stream.Start()
		tb.startWG.Done()

		tb.watch(stream, namespace, fileNamer)
	}()
}

// getRootDirAndNamespace computes the root and namespace for the log directory.
//
// May block for a short time to wait to guess the root directory.
func (tb *TBHandler) getRootDirAndNamespace(
	explicitRootDir *RootDir,
	logDir *LocalOrCloudPath,
) (*RootDir, string) {
	// Use the explicit directory if given.
	if explicitRootDir != nil {
		return explicitRootDir, tb.namespaceFrom(explicitRootDir, logDir)
	}

	// Try guessing based on logging directories.
	if rootDir := tb.rootDirGuesser.InferRootOrTimeout(
		logDir,
		10*time.Second,
	); rootDir != nil {
		return rootDir, tb.namespaceFrom(rootDir, logDir)
	}

	// Try using the CWD, if we're on a local filesystem.
	//
	// We don't infer the namespace in this case, since it's likely
	// to be ugly like "runs/CURRENT_DATETIME_HOSTNAME".
	if logDir.LocalPath != nil {
		if rootDir, err := RootDirFromCWD(); err != nil {
			tb.logger.Warn(
				"tensorboard: failed to use current working directory"+
					" as the root directory",
				"error", err)
		} else {
			return rootDir, ""
		}
	}

	return nil, ""
}

// namespaceFrom computes the namespace for a logging directory given
// a root directory.
//
// On error, warns and returns an empty string.
func (tb *TBHandler) namespaceFrom(
	rootDir *RootDir,
	logDir *LocalOrCloudPath,
) string {
	namespace, err := rootDir.TrimFrom(logDir)

	if err != nil {
		tb.logger.Warn(
			"tensorboard: failed to compute namespace",
			"error", err)
		return ""
	}

	return namespace
}

// watch consumes the TF event stream, uploading tfevents files
// and logging events to the run.
func (tb *TBHandler) watch(
	stream *tfEventStream,
	namespace string,
	fileNamer FileNamer,
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
		tb.saveFiles(stream.Files(), fileNamer)
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

	// Combine events with the same step into the same W&B step.
	//
	// The purpose of this is mainly aesthetic, as it makes graphs against
	// the W&B step a bit nicer. It may also have a positive effect on the
	// storage usage of a run by producing a more dense history.
	//
	// When doing this, we assume that consecutive events with the same step
	// number do not have overlapping data, or else the latest value is taken.
	// We similarly assume that the "wall time" is roughly the same for such
	// events.
	//
	// Since different events in the same file can use the step to represent
	// different quantities, this will sometimes merge unrelated events
	// into the same W&B step. For example, Keras logs "epoch_loss" and
	// "evaluation_loss_vs_iterations" during a validation run, which use
	// the epoch and the iteration as the event step respectively. In this
	// case, we assume such events don't have overlapping tags.
	var emitter *tfEmitter
	var emitterStep int64

	for event := range events {
		tb.logger.Debug(
			"tensorboard: processed event",
			"event", event,
			"namespace", namespace,
		)

		if emitter == nil {
			emitter = NewTFEmitter(tb.settings)
			emitterStep = event.Step
		} else if emitterStep != event.Step {
			emitter.Emit(tb.extraWork)
			emitter = NewTFEmitter(tb.settings)
			emitterStep = event.Step
		}

		converter.ConvertNext(emitter, event, tb.logger)
	}

	if emitter != nil {
		emitter.Emit(tb.extraWork)
	}
}

func (tb *TBHandler) saveFiles(
	files <-chan *LocalOrCloudPath,
	fileNamer FileNamer,
) {
	if fileNamer == nil {
		for range files {
		}
		return
	}

	for file := range files {
		if file.LocalPath == nil {
			tb.logger.Warn(
				"tensorboard: not saving tfevents file because it is in"+
					" the cloud",
				"file", file.CloudPath)
			continue
		}
		localPath := *file.LocalPath

		runPath, err := fileNamer(file)

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
	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{Policy: spb.FilesItem_END, Path: runPath},
				},
			},
		},
	}
	tb.extraWork.AddWork(runwork.NoRequest(runwork.WorkFromRecord(record)))
}
