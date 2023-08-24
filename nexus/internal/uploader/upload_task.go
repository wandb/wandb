package uploader

import "sync"

// UploadTask is a task to upload a file
type UploadTask struct {

	// Path is the path to the file
	Path string

	// Url is the endpoint to upload to
	Url string

	// Headers to send on the upload
	Headers []string

	// allow tasks to wait for completion (failed or success)
	WgOutstanding *sync.WaitGroup
}

func (t *UploadTask) outstandingAdd() {
	if t.WgOutstanding == nil {
		return
	}
	t.WgOutstanding.Add(1)
}

func (t *UploadTask) outstandingDone() {
	if t.WgOutstanding == nil {
		return
	}
	t.WgOutstanding.Done()
}
