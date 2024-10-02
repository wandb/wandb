package filetransfer

import (
	"context"
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
)

const (
	DefaultRetryMax     = 20
	DefaultRetryWaitMin = 2 * time.Second
	DefaultRetryWaitMax = 60 * time.Second
	// wait forever by default
	DefaultNonRetryTimeout = 0 * time.Second
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
