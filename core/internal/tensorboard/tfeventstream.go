package tensorboard

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/paths"
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
	files  chan paths.AbsolutePath

	done chan struct{}
	wg   sync.WaitGroup
}

func NewTFEventStream(
	logDir paths.AbsolutePath,
	readDelay waiting.Delay,
	fileFilter TFEventsFileFilter,
	logger *observability.CoreLogger,
) *tfEventStream {
	return &tfEventStream{
		readDelay: readDelay,
		logger:    logger,

		reader: NewTFEventReader(logDir, fileFilter, logger),

		events: make(chan *tbproto.TFEvent),
		files:  make(chan paths.AbsolutePath),

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
func (s *tfEventStream) Files() <-chan paths.AbsolutePath {
	return s.files
}

func (s *tfEventStream) emitFilePath(path paths.AbsolutePath) {
	s.files <- path
}

// Stop reads all remaining events and stops after reaching EOF.
func (s *tfEventStream) Stop() {
	close(s.done)
	s.wg.Wait()

	close(s.files)
	close(s.events)
}

// Start begins reading files and pushing to the output channel.
//
// A no-op if called after Stop.
func (s *tfEventStream) Start() {
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.loop()
	}()
}

func (s *tfEventStream) loop() {
	// Whether we're in the final stage where we read all remaining events.
	//
	// Stop() may be invoked while we're asleep, during which time more events
	// may have been written. As soon as Stop() is invoked, we wake up and
	// flush all remaining events before exiting the loop.
	isFinishing := false

	for {
		event, err := s.reader.NextEvent(s.emitFilePath /*onNewFile*/)
		if err != nil {
			s.logger.CaptureError(
				fmt.Errorf(
					"tensorboard: failed reading next event: %v",
					err,
				))
			return
		}

		if event == nil {
			if isFinishing {
				return
			}

			select {
			case <-s.readDelay.Wait():
				continue
			case <-s.done:
				isFinishing = true
				continue
			}
		}

		s.events <- event
	}
}
