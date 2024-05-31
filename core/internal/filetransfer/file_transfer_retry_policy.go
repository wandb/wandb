package filetransfer

import (
	"context"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
)

// FileTransferRetryPolicy is the retry policy to be used for file operations.
func FileTransferRetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	// TODO(WB-18702): Add explicit cases for (non-)retryable errors.

	return retryablehttp.ErrorPropagatedRetryPolicy(ctx, resp, err)
}
