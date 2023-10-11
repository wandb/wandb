package filetransfer

// DownloadTask is a task to download a file
type DownloadTask struct {
	// Path is the path to save the file
	Path string

	// Url is the endpoint to download from
	Url string

	// FileType is the type of file
	FileType FileType

	// Error, if any.
	Err error

	// Callback to execute after completion (success or failure).
	CompletionCallback func(*DownloadTask)
}
