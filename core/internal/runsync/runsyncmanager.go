package runsync

import (
	"fmt"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunSyncManager handles sync-related requests.
type RunSyncManager struct {
	mu sync.Mutex

	nextID         int
	pendingSyncOps map[string]*RunSyncOperation
	ongoingSyncOps map[string]*RunSyncOperation

	runSyncOperationFactory *RunSyncOperationFactory
}

func NewRunSyncManager() *RunSyncManager {
	return &RunSyncManager{
		pendingSyncOps:          make(map[string]*RunSyncOperation),
		ongoingSyncOps:          make(map[string]*RunSyncOperation),
		runSyncOperationFactory: &RunSyncOperationFactory{},
	}
}

// InitSync prepares a sync operation.
func (m *RunSyncManager) InitSync(
	request *spb.ServerInitSyncRequest,
) *spb.ServerInitSyncResponse {
	m.mu.Lock()
	defer m.mu.Unlock()

	id := fmt.Sprintf("sync-%d", m.nextID)
	m.nextID++
	m.pendingSyncOps[id] = m.runSyncOperationFactory.New(
		request.Path,
		request.Cwd,
		UpdatesFromRequest(request),
		request.Live,
		request.Settings,
	)

	return &spb.ServerInitSyncResponse{Id: id}
}

// DoSync starts a sync operation and blocks until it completes.
func (m *RunSyncManager) DoSync(
	request *spb.ServerSyncRequest,
) *spb.ServerSyncResponse {
	m.mu.Lock()
	op, exists := m.pendingSyncOps[request.Id]
	if exists {
		m.ongoingSyncOps[request.Id] = op
		delete(m.pendingSyncOps, request.Id)
	}
	m.mu.Unlock()

	if !exists {
		return &spb.ServerSyncResponse{Messages: []*spb.ServerSyncMessage{{
			Severity: spb.ServerSyncMessage_SEVERITY_ERROR,
			Content: fmt.Sprintf(
				"Internal error: operation unknown or already started: %s",
				request.Id,
			),
		}}}
	}

	response := op.Do(int(request.GetParallelism()))

	m.mu.Lock()
	delete(m.ongoingSyncOps, request.Id)
	m.mu.Unlock()

	return response
}

// SyncStatus returns the status of an ongoing sync operation.
func (m *RunSyncManager) SyncStatus(
	request *spb.ServerSyncStatusRequest,
) *spb.ServerSyncStatusResponse {
	m.mu.Lock()
	defer m.mu.Unlock()

	op, exists := m.ongoingSyncOps[request.Id]
	if !exists {
		return &spb.ServerSyncStatusResponse{}
	}

	return op.Status()
}
