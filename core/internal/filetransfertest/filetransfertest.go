// Testability for the filetransfer package.
package filetransfertest

import (
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/filetransfer"
)

type FakeFileTransferManager struct {
	tasks           []filetransfer.Task
	unfinishedTasks map[filetransfer.Task]struct{}
	tasksMu         *sync.Mutex

	// Whether new tasks should be completed immediately.
	ShouldCompleteImmediately bool
}

func NewFakeFileTransferManager() *FakeFileTransferManager {
	return &FakeFileTransferManager{
		tasksMu:         &sync.Mutex{},
		unfinishedTasks: make(map[filetransfer.Task]struct{}),
	}
}

// All the tasks added via `AddTask`.
func (m *FakeFileTransferManager) Tasks() []filetransfer.Task {
	m.tasksMu.Lock()
	defer m.tasksMu.Unlock()
	return slices.Clone(m.tasks)
}

// Runs the completion callback for all incomplete tasks.
func (m *FakeFileTransferManager) CompleteTasks() {
	m.tasksMu.Lock()
	defer m.tasksMu.Unlock()

	for task := range m.unfinishedTasks {
		task.Complete(nil)
		delete(m.unfinishedTasks, task)
	}
}

//
// FileTransferManager interface implementation
//

func (m *FakeFileTransferManager) Start() {}

func (m *FakeFileTransferManager) Close() {
	m.CompleteTasks()
}

func (m *FakeFileTransferManager) AddTask(t filetransfer.Task) {
	m.tasksMu.Lock()
	defer m.tasksMu.Unlock()

	m.tasks = append(m.tasks, t)

	if m.ShouldCompleteImmediately {
		t.Complete(nil)
	} else {
		m.unfinishedTasks[t] = struct{}{}
	}
}
