package uploader

// UploadTask is a task to upload a file
type UploadTask struct {
	// Path is the path to the file
	Path string

	// Url is the endpoint to upload to
	Url string

	// Headers to send on the upload
	Headers []string

	// Error, if any.
	Err error

	// Callback to execute after completion (success or failure).
	CompletionCallback func(*UploadTask)
}
