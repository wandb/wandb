package filetransfer

import (
	"context"
	"fmt"
	"net/http"
)

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

	// Size is the number of bytes to upload
	//
	// If this is zero, then all bytes starting at `Offset` are uploaded; if non-zero,
	// then that many bytes starting from `Offset` are uploaded.
	Size int64

	// Offset is the beginning of the file segment to upload
	Offset int64

	// Response is the http.Response from a successful upload or download request.
	//
	// This is nil for failed requests, or requests that have not completed.
	Response *http.Response

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

func (ut *Task) String() string {
	return fmt.Sprintf(
		"Task{FileKind: %d, Type: %d, Path: %s, Name: %s, Url: %s, Size: %d}",
		ut.FileKind, ut.Type, ut.Path, ut.Name, ut.Url, ut.Size,
	)
}
