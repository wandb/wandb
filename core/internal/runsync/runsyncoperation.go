package runsync

import (
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
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
}

func (f *RunSyncOperationFactory) New(
	paths []string,
	globalSettings *spb.Settings,
) *RunSyncOperation {
	op := &RunSyncOperation{
		printer: observability.NewPrinter(),
	}

	for _, path := range paths {
		settings := MakeSyncSettings(globalSettings, path)
		factory := InjectRunSyncerFactory(settings)
		op.syncers = append(op.syncers, factory.New(path))
	}

	return op
}

// Do starts syncing and blocks until all sync work completes.
func (op *RunSyncOperation) Do(parallelism int) *spb.ServerSyncResponse {
	plan, err := op.initAndPlan()

	if err != nil {
		// TODO: Log the error.
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
					// TODO: Print this at ERROR level, not INFO.
					op.printer.Write(ToUserText(err))
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
	stats := make(map[string]*spb.OperationStats, len(op.syncers))
	for _, syncer := range op.syncers {
		syncer.AddStats(stats)
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
			Severity: spb.ServerSyncMessage_SEVERITY_INFO,
			Content:  message,
		})
	}

	for _, syncer := range op.syncers {
		messages = append(messages, syncer.PopMessages()...)
	}
	return messages
}
