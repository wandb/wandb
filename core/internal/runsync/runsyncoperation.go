package runsync

import (
	"log/slog"
	"path/filepath"
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
)

// RunSyncOperationFactory creates RunSyncOperations.
type RunSyncOperationFactory struct{}

// RunSyncOperation is a collection of RunSyncers working as part of a single
// operation.
//
// This is needed because the server can sync multiple paths simultaneously.
type RunSyncOperation struct {
	syncers []*RunSyncer
	printer *observability.Printer

	logFile *DebugSyncLogFile
	logger  *observability.CoreLogger
}

func (f *RunSyncOperationFactory) New(
	paths []string,
	cwd string,
	updates *RunSyncUpdates,
	live bool,
	globalSettings *spb.Settings,
) *RunSyncOperation {
	op := &RunSyncOperation{
		printer: observability.NewPrinter(),
	}

	logFile, err := OpenDebugSyncLogFile(settings.From(globalSettings))
	if err != nil {
		slog.Error("runsync: couldn't create log file", "error", err)
	}
	op.logFile = logFile
	op.logger = NewSyncLogger(logFile, slog.LevelInfo)

	for _, userPath := range paths {
		var path string
		switch {
		case filepath.IsAbs(userPath):
			path = userPath
		case filepath.IsAbs(cwd):
			path = filepath.Join(cwd, userPath)
		default:
			op.printer.Errorf("Failed to resolve %q, skipping.", userPath)
			continue
		}

		settings := MakeSyncSettings(globalSettings, userPath)
		factory := InjectRunSyncerFactory(settings, op.logger)
		op.syncers = append(op.syncers,
			factory.New(path, ToDisplayPath(userPath, cwd), updates, live))
	}

	return op
}

// Do starts syncing and blocks until all sync work completes.
func (op *RunSyncOperation) Do(parallelism int) *spb.ServerSyncResponse {
	defer op.logFile.Close()

	plan, err := op.initAndPlan()

	if err != nil {
		LogSyncFailure(op.logger, err)
		return &spb.ServerSyncResponse{
			Messages: []*spb.ServerSyncMessage{ToSyncErrorMessage(err)},
		}
	}

	group := &errgroup.Group{}
	group.SetLimit(parallelism)

	for _, syncers := range plan {
		group.Go(func() error {
			for _, syncer := range syncers {
				err := syncer.Sync()

				if err != nil {
					LogSyncFailure(op.logger, err)
					op.printer.Errorf("%s", ToUserText(err))
					break
				}
			}
			return nil
		})
	}

	_ = group.Wait()

	return &spb.ServerSyncResponse{
		Messages: op.popMessages(),
	}
}

// initAndPlan inits all syncers and returns the order in which to run them.
//
// The return value is a map from run paths to lists of syncers.
// Different paths can be synced independently, but all syncers for the same
// path must run in order. This happens when syncing multiple resumed
// instances of the same run.
func (op *RunSyncOperation) initAndPlan() (map[string][]*RunSyncer, error) {
	type syncerAndTime struct {
		syncer    *RunSyncer
		startTime time.Time
	}

	syncerByRun := make(map[string][]syncerAndTime)
	for _, syncer := range op.syncers {
		info, err := syncer.Init()
		if err != nil {
			return nil, err
		}

		runPath := info.Path()
		syncerByRun[runPath] = append(syncerByRun[runPath], syncerAndTime{
			syncer:    syncer,
			startTime: info.StartTime,
		})
	}

	groupedOrderedSyncers := make(map[string][]*RunSyncer)
	for path, syncersAndTimes := range syncerByRun {
		// Sort by ascending start time.
		slices.SortFunc(syncersAndTimes, func(a, b syncerAndTime) int {
			return a.startTime.Compare(b.startTime)
		})

		syncers := make([]*RunSyncer, len(syncersAndTimes))
		for i := range syncersAndTimes {
			syncers[i] = syncersAndTimes[i].syncer
		}

		groupedOrderedSyncers[path] = syncers
	}

	return groupedOrderedSyncers, nil
}

// Status returns the operation's status.
func (op *RunSyncOperation) Status() *spb.ServerSyncStatusResponse {
	stats := make([]*spb.OperationStats, 0, len(op.syncers))
	for _, syncer := range op.syncers {
		stats = append(stats, syncer.Stats())
	}

	return &spb.ServerSyncStatusResponse{
		Stats:       stats,
		NewMessages: op.popMessages(),
	}
}

func (op *RunSyncOperation) popMessages() []*spb.ServerSyncMessage {
	var messages []*spb.ServerSyncMessage

	for _, message := range op.printer.Read() {
		messages = append(messages, &spb.ServerSyncMessage{
			Severity: spb.ServerSyncMessage_Severity(message.Severity),
			Content:  message.Content,
		})
	}

	for _, syncer := range op.syncers {
		messages = append(messages, syncer.PopMessages()...)
	}
	return messages
}
