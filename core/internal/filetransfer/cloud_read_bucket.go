//go:build cloud_http

package filetransfer

import (
	"context"
	"fmt"
	"io"

	"github.com/wandb/wandb/core/internal/observability"
)

// CloudObjectPage contains one page of object names, sorted by UTF-8 key.
// NextToken is empty after the last page.
type CloudObjectPage struct {
	Keys      []string
	NextToken string
}

// CloudReadBucket is the subset of cloud storage used to follow TensorBoard
// event files. Each range reader observes the latest object when opened;
// subsequent opens may observe a newer, longer version of the same object.
// Returned readers must be closed. Offset is measured in bytes returned to
// the reader, including when the storage provider decodes content encoding.
type CloudReadBucket interface {
	ListPage(ctx context.Context, prefix, token string) (CloudObjectPage, error)
	NewRangeReader(ctx context.Context, key string, offset int64) (io.ReadCloser, error)
}

// OpenCloudReadBucket shares the artifact HTTP transports and credential
// providers with TensorBoard, without linking the generated storage SDKs.
func OpenCloudReadBucket(
	ctx context.Context,
	scheme, bucket string,
	logger *observability.CoreLogger,
) (CloudReadBucket, error) {
	if bucket == "" {
		return nil, fmt.Errorf("cloud storage: bucket must not be empty")
	}
	switch scheme {
	case "s3":
		return newS3ReadBucket(ctx, bucket, logger)
	case "gs":
		return newGCSReadBucket(ctx, bucket, logger)
	case "azblob":
		return newAzureReadBucket(ctx, bucket, logger)
	default:
		return nil, fmt.Errorf("cloud storage: unsupported scheme %q", scheme)
	}
}
