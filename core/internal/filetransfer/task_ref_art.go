package filetransfer

import (
	"fmt"
	"net/url"
	"strings"
)

// ReferenceArtifactTask is a task to upload/download a reference artifacts
type ReferenceArtifactTask struct {
	OnComplete TaskCompletionCallback

	// FileKind is the category of file being uploaded or downloaded
	FileKind RunFileKind

	// PathOrPrefix is either the full local path to the file, or in the case
	// when the artifact was uploaded with `checksum=False`, the path to the
	// folder where the files will be downloaded, aka the path prefix
	PathOrPrefix string

	// Size is the number of bytes the reference object is
	Size int64

	// Error, if any.
	Err error

	// Reference to the artifact being transfered
	Reference string

	// VersionId is the version of the file we want to download. Different
	// cloud providers use different types of versions, so we store this as
	// an interface and determine the type based on the reference
	VersionId interface{}

	// Digest is the checksum to ensure the correct files are being downloaded
	//
	// This is the same as Reference when the artifact was uploaded with
	// `checksum=False`, and indicates we need to download every object
	// that has Reference as a prefix.
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
			Path:          t.PathOrPrefix,
			UploadedBytes: t.Size,
			TotalBytes:    t.Size,
		})
	}
}
func (t *ReferenceArtifactUploadTask) String() string {
	return fmt.Sprintf(
		"ReferenceArtifactUploadTask{Path: %s, Ref: %s, Size: %d}",
		t.PathOrPrefix, t.Reference, t.Size,
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
		t.PathOrPrefix, t.Reference, t.Size,
	)
}
func (t *ReferenceArtifactDownloadTask) SetError(err error) { t.Err = err }

func (t *ReferenceArtifactDownloadTask) HasSingleFile() bool { return t.Digest != t.Reference }

func (t *ReferenceArtifactDownloadTask) ShouldCheckDigest() bool { return t.Digest != t.Reference }

func (t *ReferenceArtifactDownloadTask) SetVersionID(val any) error {
	switch val.(type) {
	case string, int64, float64:
		t.VersionId = val
	default:
		return fmt.Errorf("reference artifact task: error setting version id of unexpected type: %v", val)
	}
	return nil
}

func (t *ReferenceArtifactDownloadTask) VersionIDNumber() (int64, bool) {
	floatVal, ok := t.VersionId.(float64)
	if ok {
		return int64(floatVal), ok
	}
	intVal, ok := t.VersionId.(int64)
	return intVal, ok
}

func (t *ReferenceArtifactDownloadTask) VersionIDString() (string, bool) {
	strVersionId, ok := t.VersionId.(string)
	return strVersionId, ok
}

func getStorageProvider(ref string, fts *FileTransfers) (ReferenceArtifactFileTransfer, error) {
	uriParts, err := url.Parse(ref)
	switch {
	case err != nil:
		return nil, err
	case uriParts.Scheme == "gs":
		return fts.GCS, nil
	case uriParts.Scheme == "s3":
		return fts.S3, nil
	default:
		return nil, fmt.Errorf("reference artifact task: unknown reference type: %s", ref)
	}
}

// parseReference parses the reference path and returns the bucket name and
// object name.
func parseCloudReference(
	reference string,
	expectedScheme string,
) (string, string, error) {
	uriParts, err := url.Parse(reference)
	if err != nil {
		return "", "", err
	}
	if uriParts.Scheme != expectedScheme {
		err := fmt.Errorf("invalid %s URI %s", expectedScheme, reference)
		return "", "", err
	}
	bucketName := uriParts.Host
	objectName := strings.TrimPrefix(uriParts.Path, "/")
	return bucketName, objectName, nil
}
