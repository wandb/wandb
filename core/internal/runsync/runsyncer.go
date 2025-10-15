package runsync

import (
	"fmt"
	"sync"
	"time"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
)

var runSyncerProviders = wire.NewSet(
	wire.Struct(new(RunSyncerFactory), "*"),
)

// RunSyncerFactory creates RunSyncer.
type RunSyncerFactory struct {
	Logger              *observability.CoreLogger
	Operations          *wboperation.WandbOperations
	Printer             *observability.Printer
	RecordParserFactory *stream.RecordParserFactory
	RunReaderFactory    *RunReaderFactory
	SenderFactory       *stream.SenderFactory
	TBHandlerFactory    *tensorboard.TBHandlerFactory
}

// RunSyncer is a sync operation for one .wandb file.
type RunSyncer struct {
	mu      sync.Mutex
	runInfo *RunInfo

	path string

	logger     *observability.CoreLogger
	operations *wboperation.WandbOperations
	printer    *observability.Printer
	runReader  *RunReader
	runWork    runwork.RunWork
	sender     *stream.Sender
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

		logger:     f.Logger,
		operations: f.Operations,
		printer:    f.Printer,
		runReader:  runReader,
		runWork:    runWork,
		sender:     sender,
	}
}

// Sync uploads the .wandb file.
func (rs *RunSyncer) Sync() {
	runInfo, err := rs.runReader.ExtractRunInfo()
	if err != nil {
		// TODO: Emit error.
		logSyncFailure(rs.logger, err)
		return
	}
	rs.mu.Lock()
	rs.runInfo = runInfo
	rs.mu.Unlock()

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

	err = g.Wait()
	if err != nil {
		// TODO: Emit error.
		logSyncFailure(rs.logger, err)
	} else {
		rs.printer.Writef("Finished syncing %s", rs.path)
	}
}

// AddStats inserts the sync operation's status info into the map
// keyed by the run's path.
func (rs *RunSyncer) AddStats(status map[string]*spb.OperationStats) {
	rs.mu.Lock()
	runInfo := rs.runInfo
	rs.mu.Unlock()
	if runInfo == nil {
		return
	}

	status[runInfo.Path()] = rs.operations.ToProto()
}

// PopMessages returns any new messages for the sync operation.
func (rs *RunSyncer) PopMessages() []*spb.ServerSyncMessage {
	rs.mu.Lock()
	runInfo := rs.runInfo
	rs.mu.Unlock()
	if runInfo == nil {
		return nil
	}

	var messages []*spb.ServerSyncMessage
	for _, msg := range rs.printer.Read() {
		messages = append(messages,
			&spb.ServerSyncMessage{
				// TODO: Existing code assumes printer messages are warnings.
				Severity: spb.ServerSyncMessage_SEVERITY_INFO,
				Content:  fmt.Sprintf("[%s] %s", runInfo.Path(), msg),
			})
	}
	return messages
}
