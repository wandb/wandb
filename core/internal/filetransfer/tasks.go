package filetransfer

import "context"

type TaskType int

const (
	UploadTask TaskType = iota
	DownloadTask
)

// Task is a task to upload/download a file
type Task struct {
	// FileKind is the category of file being uploaded or downloaded
	FileKind RunFileKind

	// Type is the type of task (upload or download)
	Type TaskType

	// Path is the local path to the file
	Path string

	// Name is the name of the file
	Name string

	// Url is the endpoint to upload to/download from
	Url string

	// Headers to send on the upload
	Headers []string

	// Size is the size of the file
	Size int64

	// Offset is the offset of the file
	Offset int64

	// Length is the length of the segment to upload
	// If 0 the entire file is uploaded unless Offset > 0
	Length int64

	// Error, if any.
	Err error

	// Callback to execute after completion (success or failure).
	CompletionCallback func(*Task)

	// ProgressCallback is a callback to execute on progress updates
	ProgressCallback func(int, int)

	// This can be used to cancel the file upload or download if it is no longer needed.
	Context context.Context
}

func (ut *Task) SetProgressCallback(callback func(int, int)) {
	ut.ProgressCallback = callback
}

func (ut *Task) SetCompletionCallback(callback func(*Task)) {
	ut.CompletionCallback = callback
}
