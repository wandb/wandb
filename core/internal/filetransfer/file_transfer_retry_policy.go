package filetransfer

import (
	"context"
	"net/http"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
)

// FileTransferRetryPolicy is the retry policy to be used for file operations.
func FileTransferRetryPolicy(
	ctx context.Context,
	resp *http.Response,
	err error,
) (bool, error) {
	if err != nil {
		switch {
		// Retry dial tcp <IP>: i/o timeout errors.
		//
		// Cloud storage providers sometimes return such i/o timeout errors when rate limiting
		// without specifying the error type to prevent potential malicious attacks.
		// See https://wandb.atlassian.net/browse/WB-18702 for more context.
		case strings.Contains(err.Error(), "dial tcp") && strings.Contains(err.Error(), "i/o timeout"):
			return true, err
		// Retry context deadline exceeded errors.
		//
		// This is controlled by the _file_transfer_timeout_seconds setting.
		case strings.Contains(err.Error(), "context deadline exceeded"):
			return true, err
		// Abort on any other error from the HTTP transport.
		//
		// This happens if reading the file fails, for example if it is a directory
		// or if it doesn't exist. retryablehttp's default policy for this situation
		// is to retry, which we do not want.
		default:
			return false, err
		}
	}

	return retryablehttp.ErrorPropagatedRetryPolicy(ctx, resp, err)
}
