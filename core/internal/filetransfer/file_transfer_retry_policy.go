package filetransfer

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/url"
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
		var opErr *net.OpError
		var urlErr *url.Error
		switch {
		// Retry dial tcp <IP>: i/o timeout errors.
		//
		// Cloud storage providers sometimes return such i/o timeout errors when rate limiting
		// without specifying the error type to prevent potential malicious attacks.
		// See https://wandb.atlassian.net/browse/WB-18702 for more context.
		case errors.As(err, &opErr) && strings.Contains(err.Error(), "dial tcp") && strings.Contains(err.Error(), "i/o timeout"):
			return true, err
		case errors.As(err, &opErr) && strings.Contains(err.Error(), "read: connection reset by peer"):
			return true, err
		case errors.As(err, &urlErr) && strings.Contains(err.Error(), "unexpected EOF"):
			return true, err
		case errors.As(err, &urlErr) && strings.Contains(err.Error(), "http2: client connection force closed via ClientConn.Close"):
			return true, err
		// Retry context deadline exceeded errors.
		//
		// This is controlled by the _file_transfer_timeout_seconds setting.
		case errors.As(err, &urlErr) && strings.Contains(err.Error(), "context deadline exceeded"):
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
