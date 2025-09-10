package runsync

import (
	"time"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waiting"
	"golang.org/x/sync/errgroup"
)

var runSyncerProviders = wire.NewSet(
	wire.Struct(new(RunSyncerFactory), "*"),
)

// RunSyncerFactory creates RunSyncer.
type RunSyncerFactory struct {
	Logger              *observability.CoreLogger
	RecordParserFactory *stream.RecordParserFactory
	RunReaderFactory    *RunReaderFactory
	SenderFactory       *stream.SenderFactory
	TBHandlerFactory    *tensorboard.TBHandlerFactory
}

// RunSyncer is a sync operation for one .wandb file.
type RunSyncer struct {
	path string

	logger    *observability.CoreLogger
	runReader *RunReader
	runWork   runwork.RunWork
	sender    *stream.Sender
}

// New initializes a sync operation without starting it.
func (f *RunSyncerFactory) New(path string) *RunSyncer {
	// A small buffer helps smooth out filesystem hiccups if they happen
	// and we're processing data fast enough. This is otherwise unnecessary.
	const runWorkBufferSize = 32

	runWork := runwork.New(runWorkBufferSize, f.Logger)
	sender := f.SenderFactory.New(runWork)
	tbHandler := f.TBHandlerFactory.New(
		runWork,
		/*fileReadDelay=*/ waiting.NewDelay(5*time.Second),
	)
	recordParser := f.RecordParserFactory.New(runWork.BeforeEndCtx(), tbHandler)
	runReader := f.RunReaderFactory.New(path, recordParser, runWork)

	return &RunSyncer{
		path: path,

		logger:    f.Logger,
		runReader: runReader,
		runWork:   runWork,
		sender:    sender,
	}
}

// Sync uploads the .wandb file.
func (rs *RunSyncer) Sync() {
	g := &errgroup.Group{}

	// Process the transaction log and close RunWork at the end.
	//
	// NOTE: Closes RunWork even on error, and creates an Exit record if
	// necessary, so the Sender is guaranteed to terminate.
	g.Go(rs.runReader.ProcessTransactionLog)

	// This ends after an Exit record is emitted and RunWork is closed.
	g.Go(func() error {
		rs.sender.Do(rs.runWork.Chan())
		return nil
	})

	err := g.Wait()
	if err != nil {
		logSyncFailure(rs.logger, err)

		// TODO: Emit error.
	}
}
