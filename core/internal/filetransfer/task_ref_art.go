package filetransfer

import (
	"fmt"
	"net/url"
)

// ReferenceArtifactTask is a task to upload/download a reference artifacts
type ReferenceArtifactTask struct {
	OnComplete TaskCompletionCallback

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
func (t *ReferenceArtifactUploadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactUploadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, t.Reference, t.Size,
	)
}
func (t *ReferenceArtifactUploadTask) SetError(err error) { t.Err = err }

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
func (t *ReferenceArtifactDownloadTask) Complete(fts FileTransferStats) {
	t.OnComplete.Complete()
}
func (t *ReferenceArtifactDownloadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactDownloadTask{Path: %s, Ref: %s, Size: %d}",
		t.Path, t.Reference, t.Size,
	)
}
func (t *ReferenceArtifactDownloadTask) SetError(err error) { t.Err = err }

func getStorageProvider(ref string, fts *FileTransfers) (ReferenceArtifactFileTransfer, error) {
	uriParts, err := url.Parse(ref)
	switch {
	case err != nil:
		return nil, err
	case uriParts.Scheme == "gs":
		return fts.GCS, nil
	default:
		return nil, fmt.Errorf("reference artifact task: unknown reference type: %s", ref)
	}
}
