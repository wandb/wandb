package runsync

import (
	"sync"

	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
func (op *RunSyncOperation) Do() {
	wg := &sync.WaitGroup{}
	for _, syncer := range op.syncers {
		wg.Add(1)
		go func() {
			// TODO: Capture and log panics.
			defer wg.Done()
			syncer.Sync()
		}()
	}
	wg.Wait()
}

// Status returns the operation's status.
func (op *RunSyncOperation) Status() *spb.ServerSyncStatusResponse {
	return &spb.ServerSyncStatusResponse{
		Stats: op.operations.ToProto(),
	}
}
