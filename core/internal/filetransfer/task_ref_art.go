package filetransfer

import (
	"fmt"
	"net/url"
)

// ReferenceArtifactTask is a task to upload/download a reference artifacts
type ReferenceArtifactTask struct {
	TaskCompletionCallback

	// FileKind is the category of file being uploaded or downloaded
	FileKind RunFileKind

	// Path is the local path to the file
	Path string

	// Size is the number of bytes the reference object is
	Size int64

	// Error, if any.
	Err error

	// Reference to the artifact being transfered
	Reference string

	// VersionId is the version of the file we want to download
	VersionId interface{}

	// Digest is the checksum to ensure the correct files are being downloaded
	Digest string
}

// ReferenceArtifactUploadTask uploads a reference artifact
type ReferenceArtifactUploadTask ReferenceArtifactTask

func (t *ReferenceArtifactUploadTask) Execute(fts *FileTransfers) error {
	ft, err := getStorageProvider(t.Reference, fts)
	if err != nil {
		return err
	}

	err = ft.Upload(t)
	return err
}
func (t *ReferenceArtifactUploadTask) Complete(fts FileTransferStats) {
	t.TaskCompletionCallback.Complete(nil)
	if fts != nil {
		fts.UpdateUploadStats(FileUploadInfo{
			FileKind:      t.FileKind,
			Path:          t.Path,
			UploadedBytes: t.Size,
			TotalBytes:    t.Size,
		})
	}
}
func (t *ReferenceArtifactUploadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactUploadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, t.Reference, t.Size,
	)
}
func (t *ReferenceArtifactUploadTask) CaptureError(err error) error {
	t.Err = err
	return fmt.Errorf("filetransfer: upload: error uploading reference %s: %v", t.Reference, err)
}

// ReferenceArtifactUploadTask downloads a reference artifact
type ReferenceArtifactDownloadTask ReferenceArtifactTask

func (t *ReferenceArtifactDownloadTask) Execute(fts *FileTransfers) error {
	ft, err := getStorageProvider(t.Reference, fts)
	if err != nil {
		return err
	}

	err = ft.Download(t)
	return err
}
func (t *ReferenceArtifactDownloadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactDownloadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, t.Reference, t.Size,
	)
}
func (t *ReferenceArtifactDownloadTask) CaptureError(err error) error {
	t.Err = err
	return fmt.Errorf("filetransfer: download: error downloading reference %s: %v", t.Reference, err)
}

func getStorageProvider(ref string, fts *FileTransfers) (ReferenceArtifactFileTransfer, error) {
	uriParts, err := url.Parse(ref)
	switch {
	case err != nil:
		return nil, err
	case uriParts.Scheme == "gs":
		return fts.GCS, nil
	default:
		return nil, fmt.Errorf("filetransfer: unknown reference type: %s", ref)
	}
}
