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
	"github.com/wandb/wandb/core/internal/runsyncstate"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var runSyncPipelineProviders = wire.NewSet(
	wire.Struct(new(RunSyncPipeline), "*"),
)

// RunSyncPipeline creates the components that upload a run.
//
// It is built once the run's writer ID is read from the transaction log,
// since the ID is baked into the GraphQL and filestream clients.
type RunSyncPipeline struct {
	RecordParserFactory *stream.RecordParserFactory
	RunHandle           *runhandle.RunHandle
	SenderFactory       *stream.SenderFactory
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
	runReader  *RunReader
}

// NewRunSyncer initializes a sync operation without starting it.
func NewRunSyncer(
	path string,
	displayPath DisplayPath,
	updates *RunSyncUpdates,
	live bool,
	settings *settings.Settings,
	logger *observability.CoreLogger,
) *RunSyncer {
	operations := wboperation.NewOperations()
	runReaderFactory := &RunReaderFactory{
		Logger:     logger,
		Operations: operations,
	}

	return &RunSyncer{
		path:        path,
		displayPath: displayPath,
		settings:    settings,

		logger:     logger,
		operations: operations,
		printer:    observability.NewPrinter(printerBufferSize),
		runReader:  runReaderFactory.New(path, displayPath, updates, live),
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

	// NOTE: Print after setting runInfo for a useful message prefix.
	if version.Compare(runInfo.SDKVersion, version.Version) > 0 {
		rs.printer.Warnf(
			"Syncing a run generated with a newer SDK version (%s) may"+
				" not work as expected.",
			version.PyPI(runInfo.SDKVersion),
		)
	}

	return runInfo, nil
}

// Sync uploads the .wandb file.
//
// Init must have succeeded.
func (rs *RunSyncer) Sync(ctx context.Context) error {
	rs.mu.Lock()
	runInfo := rs.runInfo
	rs.mu.Unlock()

	// Transaction logs from older SDK versions don't record the writer.
	clientID := sharedmode.ClientID(runInfo.WriterID)
	if clientID == "" {
		clientID = sharedmode.RandomClientID()
	}

	pipeline := InjectRunSyncPipeline(
		rs.settings,
		rs.logger,
		rs.printer,
		rs.operations,
		clientID,
	)
	runHandle := pipeline.RunHandle
	runHandle.UpdateTelemetry(&spb.TelemetryRecord{
		Feature: &spb.Feature{
			Sync2: true,
		},
	})

	// A small buffer helps smooth out filesystem hiccups if they happen
	// and we're processing data fast enough. This is otherwise unnecessary.
	const runWorkBufferSize = 32

	runWork := runwork.New(runWorkBufferSize, rs.logger)
	sender := pipeline.SenderFactory.New(runWork)
	tbHandler := pipeline.TBHandlerFactory.New(
		runWork,
		/*fileReadDelay=*/ 5*time.Second,
	)
	recordParser := pipeline.RecordParserFactory.New(
		runWork.BeforeEndCtx(),
		tbHandler,
		runsyncstate.File(rs.path),
	)

	g := &errgroup.Group{}

	// Print the run's URL once we know it.
	g.Go(func() error {
		select {
		case <-runHandle.Ready():
			rs.printRunURL(runHandle)
		case <-runWork.BeforeEndCtx().Done():
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
		return rs.runReader.ProcessTransactionLog(ctx, recordParser, runWork)
	})

	// This ends after an Exit record is emitted and RunWork is closed.
	g.Go(func() error {
		sender.Do(runWork.Chan())
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
			"error", err)
	}
}

// printRunURL prints the URL for viewing the run.
func (rs *RunSyncer) printRunURL(runHandle *runhandle.RunHandle) {
	upserter, err := runHandle.Upserter()
	if err != nil {
		rs.logger.CaptureError("runsync", fmt.Errorf("runsync: printRunURL: %v", err))
		return
	}

	url, err := upserter.RunPath().URL(rs.settings.GetAppURL())
	if err != nil {
		rs.logger.CaptureError("runsync", fmt.Errorf("runsync: printRunURL: %v", err))
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
