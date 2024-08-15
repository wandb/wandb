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
	GetCompletionCallback() func(Task)

	// Methods to work with the Task
	// SetProgressCallback(func(int, int))
	SetCompletionCallback(func(Task))
	SetErr(error)
	String() string

	Execute(*FileTransfers) error
}
