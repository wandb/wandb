package filetransfer

type TaskType int

const (
	UploadTask TaskType = iota
	DownloadTask
 )

type Task interface {
	// Methods to get shared fields
	GetFileKind() RunFileKind
	GetPath() string
	GetUrl() string
	GetSize() int64
	GetErr() error
	GetType() TaskType

	// Methods to work with the Task
	SetErr(error)
	String() string

	Execute(*FileTransfers) error
	Complete()
}

type TaskCompletionCallback struct {
	CompletionCallback func()
}

func (t TaskCompletionCallback) Complete() {
	if t.CompletionCallback == nil {
		return
	}

	t.CompletionCallback()
}
