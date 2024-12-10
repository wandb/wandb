package api

import (
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
			case resp.StatusCode >= 400:
				// Read up to 1KB of the body.
				bodyReader := NewBufferingReader(resp.Body)
				bodyPrefix, err := io.ReadAll(io.LimitReader(bodyReader, 1024))

				var body string
				if err != nil {
					body = fmt.Sprintf("error reading body: %v", err)
				} else {
					body = string(bodyPrefix)
				}

				logger.Info(
					"api: retrying HTTP error",
					"status", resp.StatusCode,
					"url", resp.Request.URL.String(),
					"body", body,
				)

				resp.Body = bodyReader.Reconstruct()

				// TODO: Report the attempt number & time to next retry.
				wboperation.Get(ctx).MarkRetryingHTTPError(resp.Status)
			}
		}

		return willRetry, err
	}
}
