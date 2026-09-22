//go:build !cloud_http

package tensorboard

import (
	"context"
	"fmt"

	"gocloud.dev/blob"

	"github.com/wandb/wandb/core/internal/observability"

	// Imported for the side-effect of registering blob.OpenBucket providers.
	_ "gocloud.dev/blob/azureblob"
	_ "gocloud.dev/blob/gcsblob"
	_ "gocloud.dev/blob/s3blob"
)

func openCloudEventBucket(
	ctx context.Context,
	path *CloudPath,
	_ *observability.CoreLogger,
) (eventBucket, error) {
	bucket, err := blob.OpenBucket(ctx, fmt.Sprintf("%s://%s", path.Scheme, path.BucketName))
	if err != nil {
		return nil, fmt.Errorf("failed to open bucket: %v", err)
	}
	if path.Path != "" {
		bucket = blob.PrefixedBucket(bucket, path.Path+"/")
	}
	return &blobEventBucket{bucket: bucket}, nil
}
