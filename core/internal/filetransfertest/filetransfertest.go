// Testability for the filetransfer package.
package filetransfertest

import (
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/filetransfer"
)

type FakeFileTransferManager struct {
	tasks   []*filetransfer.Task
	tasksMu *sync.Mutex
}

func NewFakeFileTransferManager() *FakeFileTransferManager {
	return &FakeFileTransferManager{
		tasksMu: &sync.Mutex{},
	}
}

// All the tasks added via `AddTask`.
func (m *FakeFileTransferManager) Tasks() []*filetransfer.Task {
	m.tasksMu.Lock()
	defer m.tasksMu.Unlock()
	return slices.Clone(m.tasks)
}

//
// FileTransferManager interface implementation
//

func (m *FakeFileTransferManager) Start() {}

func (m *FakeFileTransferManager) Close() {}

func (m *FakeFileTransferManager) AddTask(t *filetransfer.Task) {
	m.tasksMu.Lock()
	defer m.tasksMu.Unlock()

	m.tasks = append(m.tasks, t)
}

func (m *FakeFileTransferManager) FileStreamCallback(t *filetransfer.Task) {}
