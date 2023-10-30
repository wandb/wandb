package filetransfer

type FileType int

const (
	OtherFile FileType = iota
	WandbFile
	MediaFile
	ArtifactFile
)

type TaskType int

const (
	OtherTask TaskType = iota
	UploadTask
	DownloadTask
)

// Task is a task to upload/download a file
type Task struct {
	// TaskType is the type of task (upload or download)
	TaskType TaskType

	// Path is the local path to the file
	Path string

	// Name is the name of the file
	Name string

	// Url is the endpoint to upload to/download from
	Url string

	// Headers to send on the upload
	Headers []string

	// FileType is the type of file
	FileType FileType

	// Error, if any.
	Err error

	// Callback to execute after completion (success or failure).
	CompletionCallback func(*Task)
}
