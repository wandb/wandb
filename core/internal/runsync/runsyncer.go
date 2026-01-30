package runsync

import (
	"context"
	"fmt"
	"os"
	"sync"
	"time"

	"github.com/google/wire"
	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	RunHandle           *runhandle.RunHandle
	RunReaderFactory    *RunReaderFactory
	SenderFactory       *stream.SenderFactory
	Settings            *settings.Settings
	TBHandlerFactory    *tensorboard.TBHandlerFactory
}

// RunSyncer is a sync operation for one .wandb file.
type RunSyncer struct {
	mu      sync.Mutex
	runInfo *RunInfo

	path        string
	displayPath DisplayPath
	settings    *settings.Settings

	logger     *observability.CoreLogger
	operations *wboperation.WandbOperations
	printer    *observability.Printer
	runHandle  *runhandle.RunHandle
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
		path:        path,
		displayPath: displayPath,
		settings:    f.Settings,

		logger:     f.Logger,
		operations: f.Operations,
		printer:    f.Printer,
		runHandle:  f.RunHandle,
		runReader:  runReader,
		runWork:    runWork,
		sender:     sender,
	}
}

// Init loads basic information about the run being synced.
func (rs *RunSyncer) Init(ctx context.Context) (*RunInfo, error) {
	runInfo, err := rs.runReader.ExtractRunInfo(ctx)
	if err != nil {
		return nil, err
	}

	rs.mu.Lock()
	rs.runInfo = runInfo
	rs.mu.Unlock()

	return runInfo, nil
}

// Sync uploads the .wandb file.
func (rs *RunSyncer) Sync(ctx context.Context) error {
	g := &errgroup.Group{}

	// Print the run's URL once we know it.
	g.Go(func() error {
		select {
		case <-rs.runHandle.Ready():
			rs.printRunURL()
		case <-rs.runWork.BeforeEndCtx().Done():
			rs.logger.Error("runsync: didn't print run URL, handle never became ready")
		case <-ctx.Done():
			// Cancelled, do nothing.
		}

		return nil
	})

	// Process the transaction log and close RunWork at the end.
	//
	// NOTE: Closes RunWork even on error, and creates an Exit record if
	// necessary, so the Sender is guaranteed to terminate.
	g.Go(func() error {
		return rs.runReader.ProcessTransactionLog(ctx)
	})

	// This ends after an Exit record is emitted and RunWork is closed.
	g.Go(func() error {
		rs.sender.Do(rs.runWork.Chan())
		return nil
	})

	err := g.Wait()
	if err != nil {
		return err
	}

	// NOTE: The Sender may fail to upload a run, but we still mark it synced.
	// This is not the desired behavior; we just lack an error propagation
	// mechanism.
	rs.markSynced()

	rs.printer.Infof("Finished syncing %s", rs.displayPath)
	return nil
}

// markSynced creates the .synced file to mark the run as successfully synced.
func (rs *RunSyncer) markSynced() {
	// 666 = read-writable by all (the umask generally turns this into 644)
	err := os.WriteFile(rs.path+".synced", nil, 0o666)
	if err != nil {
		rs.logger.Error(
			"runsync: couldn't create .synced file",
			"error", err,
			"path", rs.path)
	}
}

// printRunURL prints the URL for viewing the run.
func (rs *RunSyncer) printRunURL() {
	upserter, err := rs.runHandle.Upserter()
	if err != nil {
		rs.logger.CaptureError(fmt.Errorf("runsync: printRunURL: %v", err))
		return
	}

	url, err := upserter.RunPath().URL(rs.settings.GetAppURL())
	if err != nil {
		rs.logger.CaptureError(fmt.Errorf("runsync: printRunURL: %v", err))
		return
	}

	displayName := upserter.DisplayName()

	if displayName != "" {
		rs.printer.Infof("View run %s at %s", displayName, url)
	} else {
		rs.printer.Infof("View run at %s", url)
	}
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
