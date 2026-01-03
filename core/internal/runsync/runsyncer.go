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

	displayPath DisplayPath

	logger     *observability.CoreLogger
	operations *wboperation.WandbOperations
	printer    *observability.Printer
	runReader  *RunReader
	runWork    runwork.RunWork
	sender     *stream.Sender
}

// New initializes a sync operation without starting it.
func (f *RunSyncerFactory) New(
	path string,
	displayPath DisplayPath,
	updates *RunSyncUpdates,
	live bool,
) *RunSyncer {
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
	runReader := f.RunReaderFactory.New(
		path,
		displayPath,
		updates,
		live,
		recordParser,
		runWork,
	)

	return &RunSyncer{
		displayPath: displayPath,

		logger:     f.Logger,
		operations: f.Operations,
		printer:    f.Printer,
		runReader:  runReader,
		runWork:    runWork,
		sender:     sender,
	}
}

// Init loads basic information about the run being synced.
func (rs *RunSyncer) Init() (*RunInfo, error) {
	runInfo, err := rs.runReader.ExtractRunInfo()
	if err != nil {
		return nil, err
	}

	rs.mu.Lock()
	rs.runInfo = runInfo
	rs.mu.Unlock()

	return runInfo, nil
}

// Sync uploads the .wandb file.
func (rs *RunSyncer) Sync() error {
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
		return err
	}

	rs.printer.Infof("Finished syncing %s", rs.displayPath)
	return nil
}

// Stats returns the sync operation's status info, labeled as necessary.
func (rs *RunSyncer) Stats() *spb.OperationStats {
	operationsProto := rs.operations.ToProto()

	rs.mu.Lock()
	runInfo := rs.runInfo
	rs.mu.Unlock()

	if runInfo != nil {
		operationsProto.Label = runInfo.Path()
	} else {
		operationsProto.Label = string(rs.displayPath)
	}

	return operationsProto
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
				Severity: spb.ServerSyncMessage_Severity(msg.Severity),
				Content:  fmt.Sprintf("[%s] %s", runInfo.Path(), msg.Content),
			})
	}
	return messages
}
