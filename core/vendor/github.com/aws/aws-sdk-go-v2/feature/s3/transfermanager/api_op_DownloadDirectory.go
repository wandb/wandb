package transfermanager

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// DownloadDirectoryInput represents a request to the DownloadDirectory() call
type DownloadDirectoryInput struct {
	// Bucket where objects are downloaded from
	Bucket *string

	// The destination directory to download
	Destination *string

	// The S3 key prefix to use for listing objects. If not provided,
	// all objects under a bucket will be retrieved
	KeyPrefix *string

	// A callback func to allow users to fileter out unwanted objects
	// according to bool returned from the function
	Filter ObjectFilter

	// A callback function to allow customers to update individual
	// GetObjectInput that the S3 Transfer Manager generates
	Callback GetRequestCallback

	// A callback function to allow users to control the download behavior
	// when there are failed objects. The directory download will be terminated
	// if its function returns non-nil error and will continue skipping current
	// failed object if the function returns nil
	FailurePolicy DownloadDirectoryFailurePolicy
}

// ObjectFilter is the callback to allow users to filter out unwanted objects.
// It is invoked for each object listed.
type ObjectFilter interface {
	// FilterObject take the Object struct and decides if the
	// object should be downloaded
	FilterObject(s3types.Object) bool
}

// GetRequestCallback is the callback mechanism to allow customers to update
// individual GetObjectInput that the S3 Transfer Manager generates
type GetRequestCallback interface {
	// UpdateRequest preprocesses each GetObjectInput as customized
	UpdateRequest(*GetObjectInput)
}

// DownloadDirectoryFailurePolicy is a callback to allow users to control the
// download behavior when there are failed objects. It is invoked for every failed object.
// If the OnDownloadFailed returns non-nil error, downloader will cancel all ongoing
// single object download requests and terminate the download directory process, if it returns nil
// error, downloader will count the current request as a failed object downloaded but continue
// getting other objects.
type DownloadDirectoryFailurePolicy interface {
	OnDownloadFailed(*DownloadDirectoryInput, *GetObjectInput, error) error
}

// TerminateDownloadPolicy implements DownloadDirectoryFailurePolicy to cancel all other ongoing
// objects download and terminate the download directory call
type TerminateDownloadPolicy struct{}

// OnDownloadFailed returns the initial err
func (TerminateDownloadPolicy) OnDownloadFailed(directoryInput *DownloadDirectoryInput, objectInput *GetObjectInput, err error) error {
	return err
}

// IgnoreDownloadFailurePolicy implements the DownloadDirectoryFailurePolicy to ignore single object download error
// and continue downloading other objects
type IgnoreDownloadFailurePolicy struct{}

// OnDownloadFailed ignores input error and return nil
func (IgnoreDownloadFailurePolicy) OnDownloadFailed(*DownloadDirectoryInput, *GetObjectInput, error) error {
	return nil
}

// DownloadDirectoryOutput represents a response from the DownloadDirectory() call
type DownloadDirectoryOutput struct {
	// Total number of objects successfully downloaded
	ObjectsDownloaded int64

	// Total number of objects failed to download
	ObjectsFailed int64
}

type objectEntry struct {
	key  string
	path string
}

// DownloadDirectory traverses a s3 bucket and intelligently downloads all valid objects
// to local directory in parallel across multiple goroutines. You can configure the concurrency,
// valid object filtering and hierarchical file naming through the Options and input parameters.
//
// Additional functional options can be provided to configure the individual directory
// download. These options are copies of the original Options instance, the client of which DownloadDirectory is called from.
// Modifying the options will not impact the original Client and Options instance.
func (c *Client) DownloadDirectory(ctx context.Context, input *DownloadDirectoryInput, opts ...func(*Options)) (*DownloadDirectoryOutput, error) {
	fileInfo, err := os.Stat(aws.ToString(input.Destination))
	if err != nil {
		if !errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("error when getting destination folder info: %v", err)
		}
	} else if !fileInfo.IsDir() {
		return nil, fmt.Errorf("the destination path %s doesn't point to a valid directory", aws.ToString(input.Destination))

	}

	i := directoryDownloader{c: c, in: input, options: c.options.Copy()}
	for _, opt := range opts {
		opt(&i.options)
	}

	return i.downloadDirectory(ctx)
}

type directoryDownloader struct {
	c             *Client
	options       Options
	in            *DownloadDirectoryInput
	failurePolicy DownloadDirectoryFailurePolicy

	objectsDownloaded atomic.Int64
	objectsFailed     atomic.Int64

	err error

	mu           sync.Mutex
	wg           sync.WaitGroup
	progressOnce sync.Once

	emitter *directoryObjectsProgressEmitter
}

func (d *directoryDownloader) downloadDirectory(ctx context.Context) (*DownloadDirectoryOutput, error) {
	d.init()
	ch := make(chan objectEntry)

	for i := 0; i < d.options.Concurrency; i++ {
		d.wg.Add(1)
		go d.downloadObject(ctx, ch)
	}

	isTruncated := true
	continuationToken := ""
	for isTruncated {
		if d.getErr() != nil {
			break
		}
		listOutput, err := d.options.S3.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            d.in.Bucket,
			Prefix:            d.in.KeyPrefix,
			ContinuationToken: nzstring(continuationToken),
		})
		if err != nil {
			d.setErr(fmt.Errorf("error when listing objects %v", err))
			break
		}

		for _, o := range listOutput.Contents {
			if d.getErr() != nil {
				break
			}
			key := aws.ToString(o.Key)
			if strings.HasSuffix(key, "/") {
				continue // skip folder object
			}
			if d.in.Filter != nil && !d.in.Filter.FilterObject(o) {
				continue
			}
			path, err := d.getLocalPath(key)
			if err != nil {
				d.setErr(fmt.Errorf("error when resolving local path for object %s, %v", key, err))
				break
			}
			ch <- objectEntry{key, path}
		}

		continuationToken = aws.ToString(listOutput.NextContinuationToken)
		isTruncated = aws.ToBool(listOutput.IsTruncated)
	}

	close(ch)
	d.wg.Wait()

	if d.err != nil {
		freshCtx, cancel := d.freshContext(ctx)
		defer cancel()
		d.emitter.Failed(freshCtx, d.in, d.err)
		return nil, d.err
	}

	out := &DownloadDirectoryOutput{
		ObjectsDownloaded: d.objectsDownloaded.Load(),
		ObjectsFailed:     d.objectsFailed.Load(),
	}

	d.emitter.Complete(ctx, out)

	return out, nil
}

func (d *directoryDownloader) init() {
	d.failurePolicy = TerminateDownloadPolicy{}
	if d.in.FailurePolicy != nil {
		d.failurePolicy = d.in.FailurePolicy
	}

	d.emitter = &directoryObjectsProgressEmitter{
		Listeners: d.options.DirectoryProgressListeners,
	}
}

func (d *directoryDownloader) getLocalPath(key string) (string, error) {
	keyprefix := aws.ToString(d.in.KeyPrefix)
	delimiter := "/"
	destination := aws.ToString(d.in.Destination)
	if keyprefix != "" && !strings.HasSuffix(keyprefix, delimiter) {
		keyprefix = keyprefix + delimiter
	}
	path := filepath.Join(destination, strings.ReplaceAll(strings.TrimPrefix(key, keyprefix), delimiter, string(os.PathSeparator)))
	relPath, err := filepath.Rel(destination, path)
	if err != nil {
		return "", err
	}
	if relPath == "." || strings.Contains(relPath, "..") {
		return "", fmt.Errorf("resolved local path %s is outside of destination %s", path, destination)
	}

	return path, nil
}

func (d *directoryDownloader) downloadObject(ctx context.Context, ch chan objectEntry) {
	defer d.wg.Done()
	for {
		data, ok := <-ch
		if !ok {
			break
		}

		select {
		case <-ctx.Done():
			d.setErr(fmt.Errorf("context error: %v", ctx.Err()))
			continue
		default:
		}

		if d.getErr() != nil {
			continue
		}

		input := &GetObjectInput{
			Bucket: d.in.Bucket,
			Key:    aws.String(data.key),
		}
		if d.in.Callback != nil {
			d.in.Callback.UpdateRequest(input)
		}
		out, err := d.c.GetObject(ctx, input)
		if err != nil {
			err = d.failurePolicy.OnDownloadFailed(d.in, input, err)
			if err != nil {
				d.setErr(fmt.Errorf("error when heading info of object %s: %v", data.key, err))
			} else {
				d.objectsFailed.Add(1)
			}
			continue
		}

		d.progressOnce.Do(func() {
			d.emitter.Start(ctx, d.in)
		})

		err = os.MkdirAll(filepath.Dir(data.path), 0755)
		if err != nil {
			d.setErr(fmt.Errorf("error when creating directory for file %s: %v", data.path, err))
			continue
		}
		file, err := os.Create(data.path)
		if err != nil {
			d.setErr(fmt.Errorf("error when creating file %s: %v", data.path, err))
			continue
		}
		n, err := io.Copy(file, out.Body)
		if err != nil {
			// where s3.GetObject is really called, must be handled by failure policy
			err = d.failurePolicy.OnDownloadFailed(d.in, input, err)
			if err != nil {
				d.setErr(fmt.Errorf("error when getting object and writing to local file %s: %v", data.path, err))
			} else {
				d.objectsFailed.Add(1)
			}
			os.Remove(data.path)
			continue
		}

		d.objectsDownloaded.Add(1)
		d.emitter.ObjectsTransferred(ctx, n)
	}
}

func (d *directoryDownloader) freshContext(ctx context.Context) (context.Context, context.CancelFunc) {
	if d.options.FailTimeout <= 0 {
		return ctx, func() {}
	}
	return context.WithTimeout(context.Background(), d.options.FailTimeout)
}

func (d *directoryDownloader) setErr(err error) {
	d.mu.Lock()
	defer d.mu.Unlock()

	d.err = err
}

func (d *directoryDownloader) getErr() error {
	d.mu.Lock()
	defer d.mu.Unlock()

	return d.err
}
