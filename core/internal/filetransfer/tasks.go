package filetransfer

type TaskType int

const (
	UploadTask TaskType = iota
	DownloadTask
)

// Task is a task to upload/download a file
type Task interface {
	// Execute does the action (upload/download) described by the task
	Execute(*FileTransfers) error

	// Complete executes any callbacks necessary to complete the task
	Complete(FileTransferStats)

	// String describes the task
	String() string

	// SetError sets the error on the task
	SetError(error)
}

// TaskCompletionCallback handles the completion callback for a task
type TaskCompletionCallback func()

func (t TaskCompletionCallback) Complete() {
	if t == nil {
		return
	}

	t()
}
