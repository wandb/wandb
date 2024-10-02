package filetransfer

import (
	"context"
	"fmt"
	"net/http"
)

// DefaultTask is the default task to upload/download files
type DefaultTask struct {
	OnComplete TaskCompletionCallback

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

type DefaultUploadTask DefaultTask

func (t *DefaultUploadTask) Execute(fts *FileTransfers) error {
	return fts.Default.Upload(t)
}
func (t *DefaultUploadTask) Complete(fts FileTransferStats) {
	t.OnComplete.Complete()
	if fts != nil {
		fts.UpdateUploadStats(FileUploadInfo{
			FileKind:      t.FileKind,
			Path:          t.Path,
			UploadedBytes: t.Size,
			TotalBytes:    t.Size,
		})
	}
}
func (t *DefaultUploadTask) String() string {
	return fmt.Sprintf(
		"DefaultUploadTask{FileKind: %d, Path: %s, Name: %s, Url: %s, Size: %d}",
		t.FileKind, t.Path, t.Name, t.Url, t.Size,
	)
}
func (t *DefaultUploadTask) SetError(err error) { t.Err = err }

type DefaultDownloadTask DefaultTask

func (t *DefaultDownloadTask) Execute(fts *FileTransfers) error {
	return fts.Default.Download(t)
}
func (t *DefaultDownloadTask) Complete(fts FileTransferStats) {
	t.OnComplete.Complete()
}
func (t *DefaultDownloadTask) String() string {
	return fmt.Sprintf(
		"DefaultDownloadTask{FileKind: %d, Path: %s, Name: %s, Url: %s, Size: %d}",
		t.FileKind, t.Path, t.Name, t.Url, t.Size,
	)
}
func (t *DefaultDownloadTask) SetError(err error) { t.Err = err }
