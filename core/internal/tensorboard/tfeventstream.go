package tensorboard

import (
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
)

// tfEventStream creates a stream of TFEvent protos from a TensorBoard
// log directory.
//
// It has two output channels that must be consumed: `Events` and `Files`.
type tfEventStream struct {
	// readDelay is how long to wait before checking for a new event.
	readDelay waiting.Delay
	logger    *observability.CoreLogger

	reader *TFEventReader
	events chan *tbproto.TFEvent
	files  chan string

	done chan struct{}
	wg   sync.WaitGroup
}

func NewTFEventStream(
	logDir string,
	readDelay waiting.Delay,
	fileFilter TFEventsFileFilter,
	logger *observability.CoreLogger,
) *tfEventStream {
	return &tfEventStream{
		readDelay: readDelay,
		logger:    logger,

		reader: NewTFEventReader(logDir, fileFilter, logger),

		events: make(chan *tbproto.TFEvent),
		files:  make(chan string),

		done: make(chan struct{}),
	}
}

// Events returns the channel of TFEvents.
func (s *tfEventStream) Events() <-chan *tbproto.TFEvent {
	return s.events
}

// Files returns the channel of tfevents file paths.
//
// The emitted paths are always absolute.
func (s *tfEventStream) Files() <-chan string {
	return s.files
}

func (s *tfEventStream) emitFilePath(path string) {
	var absPath string

	if filepath.IsAbs(path) {
		absPath = path
	} else {
		var err error
		absPath, err = filepath.Abs(path)
		if err != nil {
			s.logger.CaptureError(
				"tensorboard: failed to make path absolute",
				err,
			)
			return
		}
	}

	s.files <- absPath
}

// Stop reads all remaining events and stops after reaching EOF.
func (s *tfEventStream) Stop() {
	close(s.done)
	s.wg.Wait()

	close(s.files)
	close(s.events)
}

// Start begins reading files and pushing to the output channel.
func (s *tfEventStream) Start() {
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.loop()
	}()
}

func (s *tfEventStream) loop() {
	for {
		event, err := s.reader.NextEvent(s.emitFilePath /*onNewFile*/)
		if err != nil {
			s.logger.CaptureError(
				"tensorboard: failed reading next event",
				err,
			)
			return
		}

		// NOTE: We only exit the loop after there are no more events to read.
		if event == nil {
			select {
			case <-s.readDelay.Wait():
				continue
			case <-s.done:
				return
			}
		}

		s.events <- event
	}
}
