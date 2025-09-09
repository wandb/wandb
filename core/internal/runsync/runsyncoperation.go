package runsync

import (
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
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
	syncers    []*RunSyncer
	operations *wboperation.WandbOperations
}

func (f *RunSyncOperationFactory) New(
	paths []string,
	settings *settings.Settings,
) *RunSyncOperation {
	op := &RunSyncOperation{}

	op.operations = wboperation.NewOperations()

	factory := InjectRunSyncerFactory(op.operations, settings)
	for _, path := range paths {
		op.syncers = append(op.syncers, factory.New(path))
	}

	return op
}

// Do starts syncing and blocks until all sync work completes.
func (op *RunSyncOperation) Do(parallelism int) {
	group := &errgroup.Group{}
	group.SetLimit(parallelism)

	for _, syncer := range op.syncers {
		group.Go(func() error {
			syncer.Sync()
			return nil
		})
	}

	_ = group.Wait()
}

// Status returns the operation's status.
func (op *RunSyncOperation) Status() *spb.ServerSyncStatusResponse {
	return &spb.ServerSyncStatusResponse{
		Stats: op.operations.ToProto(),
	}
}
