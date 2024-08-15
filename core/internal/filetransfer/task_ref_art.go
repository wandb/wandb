package filetransfer

import "fmt"

type ReferenceArtifactTask struct {
	FileKind RunFileKind

	// Path is the local path to the file
	Path string

	// Size is the number of bytes to upload
	//
	// If this is zero, then all bytes starting at `Offset` are uploaded; if non-zero,
	// then that many bytes starting from `Offset` are uploaded.
	Size int64

	// Error, if any.
	Err error

	// Callback to execute after completion (success or failure).
	CompletionCallback func(Task)

	// Reference to the artifact being transfered
	Reference *string

	// VersionId is the version of the file we want to download
	VersionId interface{}

	// Digest is the checksum to ensure the correct files are being downloaded
	Digest string
}

func (t *ReferenceArtifactTask) GetFileKind() RunFileKind { return t.FileKind }
func (t *ReferenceArtifactTask) GetPath() string          { return t.Path }
func (t *ReferenceArtifactTask) GetUrl() string {
	if t.Reference != nil {
		return *t.Reference
	}
	return ""
}
func (t *ReferenceArtifactTask) GetSize() int64                    { return t.Size }
func (t *ReferenceArtifactTask) GetErr() error                     { return t.Err }
func (t *ReferenceArtifactTask) GetCompletionCallback() func(Task) { return t.CompletionCallback }

func (t *ReferenceArtifactTask) SetCompletionCallback(callback func(Task)) {
	t.CompletionCallback = callback
}

func (t *ReferenceArtifactTask) SetErr(err error) {
	t.Err = err
}

func (t *ReferenceArtifactTask) Execute(fts *FileTransfers) error {
	return nil
}

func (t *ReferenceArtifactTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, *t.Reference, t.Size,
	)
}

type ReferenceArtifactUploadTask struct{ ReferenceArtifactTask }

func (t *ReferenceArtifactUploadTask) GetStorageProvider(fts *FileTransfers) (ReferenceArtifactFileTransfer, error) {
	switch {
	case fts.GCS.CanHandle(t):
		return fts.GCS, nil
	default:
		return nil, fmt.Errorf("fileTransfer: unknown reference type: %v", t.Reference)
	}
}
func (t *ReferenceArtifactUploadTask) Execute(fts *FileTransfers) error {
	ft, err := t.GetStorageProvider(fts)
	if err != nil {
		return err
	}

	err = ft.Upload(t)
	return err
}
func (t *ReferenceArtifactUploadTask) GetType() TaskType {
	return UploadTask
}
func (t *ReferenceArtifactUploadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactUploadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, *t.Reference, t.Size,
	)
}

type ReferenceArtifactDownloadTask struct{ ReferenceArtifactTask }

func (t *ReferenceArtifactDownloadTask) GetStorageProvider(fts *FileTransfers) (ReferenceArtifactFileTransfer, error) {
	switch {
	case fts.GCS.CanHandle(t):
		return fts.GCS, nil
	default:
		return nil, fmt.Errorf("fileTransfer: unknown reference type: %v", t.Reference)
	}
}
func (t *ReferenceArtifactDownloadTask) Execute(fts *FileTransfers) error {
	ft, err := t.GetStorageProvider(fts)
	if err != nil {
		return err
	}

	err = ft.Download(t)
	return err
}
func (t *ReferenceArtifactDownloadTask) GetType() TaskType {
	return DownloadTask
}
func (t *ReferenceArtifactDownloadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactDownloadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, *t.Reference, t.Size,
	)
}
