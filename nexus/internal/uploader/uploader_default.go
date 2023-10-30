package uploader

import (
	"fmt"
	"math"
	"net/http"
	"os"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

// DefaultUploader uploads files to the server
type DefaultUploader struct {
	// client is the HTTP client for the uploader
	client *retryablehttp.Client

	// logger is the logger for the uploader
	logger *observability.NexusLogger
}

// NewDefaultUploader creates a new uploader
func NewDefaultUploader(logger *observability.NexusLogger, client *retryablehttp.Client) *DefaultUploader {
	uploader := &DefaultUploader{
		logger: logger,
		client: client,
	}
	return uploader
}

// Upload uploads a file to the server
func (u *DefaultUploader) Upload(task *UploadTask) error {
	u.logger.Debug("default uploader: uploading file", "path", task.Path, "url", task.Url)

	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			u.logger.CaptureError("uploader: error closing file", err, "path", task.Path)
		}
	}(file)

	progressReader, err := NewProgressReader(file)
	if err != nil {
		return err
	}
	req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, progressReader)
	if err != nil {
		return err
	}

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}
	fmt.Printf("Uploading file... %s\n", task.Name)
	if _, err = u.client.Do(req); err != nil {
		fmt.Println(err)
		return err
	}

	return nil
}

type ProgressReader struct {
	*os.File
	len  int
	read int
}

func NewProgressReader(file *os.File) (*ProgressReader, error) {
	stat, err := file.Stat()
	if err != nil {
		return &ProgressReader{}, err
	}
	if stat.Size() > math.MaxInt {
		return &ProgressReader{}, fmt.Errorf("file larger than %v", math.MaxInt)
	}
	return &ProgressReader{
		File: file,
		len:  int(stat.Size()),
	}, nil
}

func (pr *ProgressReader) Read(p []byte) (int, error) {
	n, err := pr.File.Read(p)
	if err != nil {
		return n, err // Return early if there's an error
	}

	pr.read += n
	pr.reportProgress()

	return n, err
}

func (pr *ProgressReader) reportProgress() {
	if pr.len == 0 {
		return
	}
	percentage := (pr.read * 100) / pr.len
	fmt.Printf("\rUploaded %d%% (%d of %d bytes)", percentage, pr.read, pr.len)
}

func (pr *ProgressReader) Len() int {
	return pr.len
}
