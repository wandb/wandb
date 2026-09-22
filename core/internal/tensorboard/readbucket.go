package tensorboard

import (
	"context"
	"io"

	"gocloud.dev/blob"
)

// eventBucket exposes only the storage operations needed to follow event
// files. Local directories and the default SDK implementation use Go CDK;
// cloud_http builds share the artifact HTTP clients for remote buckets.
type eventBucket interface {
	List() eventIterator
	NewRangeReader(ctx context.Context, key string, offset int64) (io.ReadCloser, error)
	Close() error
}

type eventIterator interface {
	Next(ctx context.Context) (string, error)
}

type blobEventBucket struct{ bucket *blob.Bucket }

func (b *blobEventBucket) List() eventIterator {
	return &blobEventIterator{iterator: b.bucket.List(nil)}
}

func (b *blobEventBucket) NewRangeReader(
	ctx context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	return b.bucket.NewRangeReader(ctx, key, offset, -1, nil)
}

func (b *blobEventBucket) Close() error { return b.bucket.Close() }

type blobEventIterator struct{ iterator *blob.ListIterator }

func (it *blobEventIterator) Next(ctx context.Context) (string, error) {
	obj, err := it.iterator.Next(ctx)
	if err != nil {
		return "", err
	}
	return obj.Key, nil
}
