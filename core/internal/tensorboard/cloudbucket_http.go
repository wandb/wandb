//go:build cloud_http

package tensorboard

import (
	"context"
	"fmt"
	"io"
	"strings"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observability"
)

type cloudEventBucket struct {
	bucket filetransfer.CloudReadBucket
	prefix string
}

func openCloudEventBucket(
	ctx context.Context,
	path *CloudPath,
	logger *observability.CoreLogger,
) (eventBucket, error) {
	bucket, err := filetransfer.OpenCloudReadBucket(ctx, path.Scheme, path.BucketName, logger)
	if err != nil {
		return nil, fmt.Errorf("failed to open bucket: %w", err)
	}
	prefix := path.Path
	if prefix != "" {
		prefix += "/"
	}
	return &cloudEventBucket{bucket: bucket, prefix: prefix}, nil
}

func (b *cloudEventBucket) List() eventIterator {
	return &cloudEventIterator{bucket: b}
}

func (b *cloudEventBucket) NewRangeReader(
	ctx context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	return b.bucket.NewRangeReader(ctx, b.prefix+key, offset)
}

func (b *cloudEventBucket) Close() error { return nil }

type cloudEventIterator struct {
	bucket   *cloudEventBucket
	keys     []string
	token    string
	finished bool
}

func (it *cloudEventIterator) Next(ctx context.Context) (string, error) {
	for len(it.keys) == 0 {
		if err := ctx.Err(); err != nil {
			return "", err
		}
		if it.finished {
			return "", io.EOF
		}
		page, err := it.bucket.bucket.ListPage(ctx, it.bucket.prefix, it.token)
		if err != nil {
			return "", err
		}
		if page.NextToken != "" && page.NextToken == it.token {
			return "", fmt.Errorf("cloud storage: listing repeated its page token")
		}
		it.keys, it.token = page.Keys, page.NextToken
		it.finished = page.NextToken == ""
	}
	key := it.keys[0]
	it.keys = it.keys[1:]
	if !strings.HasPrefix(key, it.bucket.prefix) {
		return "", fmt.Errorf("cloud storage: listed key outside requested prefix: %q", key)
	}
	return strings.TrimPrefix(key, it.bucket.prefix), nil
}
