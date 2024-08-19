package filetransfer

import (
	"context"
	"fmt"
	"net/http"
)

type DefaultTask struct {
	TaskCompletionCallback

	// FileKind is the category of file being uploaded or downloaded
	FileKind RunFileKind

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

	// ProgressCallback is a callback to execute on progress updates
	ProgressCallback func(int, int)

	// This can be used to cancel the file upload or download if it is no longer needed.
	Context context.Context
}

func (t *DefaultTask) GetFileKind() RunFileKind          { return t.FileKind }
func (t *DefaultTask) GetPath() string                   { return t.Path }
func (t *DefaultTask) GetUrl() string                    { return t.Url }
func (t *DefaultTask) GetSize() int64                    { return t.Size }
func (t *DefaultTask) GetErr() error                     { return t.Err }

func (t *DefaultTask) SetErr(err error) {
	t.Err = err
}

type DefaultUploadTask struct{ DefaultTask }

func (t *DefaultUploadTask) String() string {
	return fmt.Sprintf(
		"DefaultUploadTask{FileKind: %d, Path: %s, Name: %s, Url: %s, Size: %d}",
		t.FileKind, t.Path, t.Name, t.Url, t.Size,
	)
}
func (t *DefaultUploadTask) Execute(fts *FileTransfers) error {
	return fts.Default.Upload(t)
}
func (t *DefaultUploadTask) GetType() TaskType {
	return UploadTask
}

type DefaultDownloadTask struct{ DefaultTask }

func (t *DefaultDownloadTask) String() string {
	return fmt.Sprintf(
		"DefaultDownloadTask{FileKind: %d, Path: %s, Name: %s, Url: %s, Size: %d}",
		t.FileKind, t.Path, t.Name, t.Url, t.Size,
	)
}
func (t *DefaultDownloadTask) Execute(fts *FileTransfers) error {
	return fts.Default.Download(t)
}
func (t *DefaultDownloadTask) GetType() TaskType {
	return DownloadTask
}
