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
	// Abort on any error from the HTTP transport.
	//
	// This happens if reading the file fails, for example if it is a directory
	// or if it doesn't exist. retryablehttp's default policy for this situation
	// is to retry, which we do not want.
	if err != nil {
		return false, err
	}

	return retryablehttp.ErrorPropagatedRetryPolicy(ctx, resp, err)
}
