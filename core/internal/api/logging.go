package api

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// Logs the final response (after retries) if it's an error.
func (backend *Backend) logFinalResponseOnError(
	req *retryablehttp.Request,
	resp *http.Response,
) {
	if resp.StatusCode < 400 || backend.logger == nil {
		return
	}

	// We don't consume the response body so that the code making the request
	// can read and close it.
	backend.logger.Error(
		"HTTP error",
		"status", resp.StatusCode,
		"method", req.Method,
		"url", req.URL.String(),
	)
}

// Wraps a RetryPolicy to log retries.
func withRetryLogging(
	policy retryablehttp.CheckRetry,
	logger *slog.Logger,
) retryablehttp.CheckRetry {
	if logger == nil {
		panic("api: withRetryLogging: nil logger")
	}

	return func(ctx context.Context, resp *http.Response, err error) (bool, error) {
		willRetry, newErr := policy(ctx, resp, err)
		if newErr != nil {
			err = newErr
		}

		if willRetry {
			switch {
			case resp == nil && err == nil:
				logger.Error("api: retrying HTTP request, no error or response")

			case err != nil:
				logger.Info("api: retrying error", "error", err)
				wboperation.Get(ctx).MarkRetryingError(err)

			case resp.StatusCode >= 400:
				bodyFirstKB, err := readResponseBodyUpToLimit(resp, 1024)

				var bodyToLog string
				if err == nil {
					bodyToLog = string(bodyFirstKB)
				} else {
					bodyToLog = fmt.Sprintf("error reading body: %v", err)
				}

				logger.Info(
					"api: retrying HTTP error",
					"status", resp.StatusCode,
					"url", resp.Request.URL.String(),
					"body", bodyToLog,
				)

				// TODO: Report the attempt number & time to next retry.
				wboperation.Get(ctx).MarkRetryingHTTPError(
					resp.StatusCode,
					resp.Status,
					ErrorFromWBResponse(bodyFirstKB),
				)
			}
		}

		return willRetry, err
	}
}

// readResponseBodyUpToLimit returns the first maxBytes of the response body
// non-destructively.
func readResponseBodyUpToLimit(
	resp *http.Response,
	maxBytes int64,
) ([]byte, error) {
	var bodyBuffer bytes.Buffer
	bodyBytes, err := io.ReadAll(
		io.LimitReader(
			io.TeeReader(resp.Body, &bodyBuffer),
			maxBytes,
		))

	resp.Body = &readerAndCloser{
		Reader: io.MultiReader(&bodyBuffer, resp.Body),
		Closer: resp.Body,
	}

	return bodyBytes, err
}

type readerAndCloser struct {
	io.Reader
	io.Closer
}
