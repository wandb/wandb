package uploader

import (
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"golang.org/x/exp/slog"
)

type RetryClientOption func(rc *retryablehttp.Client)

func WithRetryClientLogger(logger *observability.NexusLogger) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.Logger = slog.NewLogLogger(logger.Logger.Handler(), slog.LevelDebug)
	}
}

func WithRetryClientRetryMax(retryMax int) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryMax = retryMax
	}
}

func WithRetryClientRetryWaitMin(retryWaitMin time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMin = retryWaitMin
	}
}

func WithRetryClientRetryWaitMax(retryWaitMax time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMax = retryWaitMax
	}
}

func NewRetryClient(opts ...RetryClientOption) *retryablehttp.Client {
	retryClient := retryablehttp.NewClient()

	for _, opt := range opts {
		opt(retryClient)
	}
	return retryClient
}

// CustomUploader uploads files to the server
type CustomUploader struct {
	// client is the HTTP client for the uploader
	client *retryablehttp.Client

	// logger is the logger for the uploader
	logger *observability.NexusLogger
}

// NewCustomUploader creates a new uploader
func NewCustomUploader(logger *observability.NexusLogger) *CustomUploader {
	retryClient := NewRetryClient(
		WithRetryClientLogger(logger),
		WithRetryClientRetryMax(10),                 // todo: make this configurable
		WithRetryClientRetryWaitMin(1*time.Second),  // todo: make this configurable
		WithRetryClientRetryWaitMax(60*time.Second), // todo: make this configurable
	)

	uploader := &CustomUploader{
		client: retryClient,
		logger: logger,
	}
	return uploader
}

// Upload uploads a file to the server
func (u *CustomUploader) Upload(task *UploadTask) error {
	u.logger.Debug("custom uploader: uploading file", "path", task.Path, "url", task.Url)
	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		task.outstandingDone()
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			u.logger.CaptureError("uploader: error closing file", err, "path", task.Path)
		}
	}(file)

	req, err := retryablehttp.NewRequest(
		http.MethodPut,
		task.Url,
		file,
	)

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if err != nil {
		task.outstandingDone()
		return err
	}

	if _, err = u.client.Do(req); err != nil {
		task.outstandingDone()
		return err
	}
	task.outstandingDone()
	return nil
}

/*
const (
	ChunkSize       = 4096 // 4KB chunks
	UploadURL       = "https://your-upload-url.com"
	MaxRetry        = 3
	RetryWaitMin    = 1000
	RetryWaitMax    = 5000
	FileParameter   = "file"
	ContentRangeFmt = "bytes %d-%d/%d"
)

func main() {
	file, err := os.Open("path/to/your/file.ext")
	if err != nil {
		log.Fatalf("Could not open file: %v", err)
	}
	defer file.Close()

	fileInfo, err := file.Stat()
	if err != nil {
		log.Fatalf("Could not get file info: %v", err)
	}
	fileSize := fileInfo.Size()

	client := retryablehttp.NewClient()
	client.RetryMax = MaxRetry
	client.RetryWaitMin = RetryWaitMin
	client.RetryWaitMax = RetryWaitMax

	chunk := make([]byte, ChunkSize)
	var start, end int64

	for {
		n, err := file.Read(chunk)
		if err != nil {
			if err == io.EOF {
				break
			}
			log.Fatalf("Could not read file chunk: %v", err)
		}

		end = start + int64(n) - 1
		contentRange := fmt.Sprintf(ContentRangeFmt, start, end, fileSize)

		body := &bytes.Buffer{}
		writer := multipart.NewWriter(body)
		part, err := writer.CreateFormFile(FileParameter, fileInfo.Name())
		if err != nil {
			log.Fatalf("Could not create form file: %v", err)
		}

		if _, err := part.Write(chunk[:n]); err != nil {
			log.Fatalf("Could not write chunk data: %v", err)
		}

		if err := writer.Close(); err != nil {
			log.Fatalf("Could not close multipart writer: %v", err)
		}

		req, err := retryablehttp.NewRequest(http.MethodPost, UploadURL, body)
		if err != nil {
			log.Fatalf("Could not create request: %v", err)
		}

		req.Header.Set("Content-Type", writer.FormDataContentType())
		req.Header.Set("Content-Range", contentRange)
		req.Header.Set("Content-Length", strconv.Itoa(body.Len()))

		resp, err := client.Do(req)
		if err != nil {
			log.Fatalf("Could not send request: %v", err)
		}
		if resp.StatusCode >= 300 {
			log.Fatalf("Received non-success status code %d", resp.StatusCode)
		}

		start += int64(n)
	}

	log.Println("File uploaded successfully.")
}

*/
