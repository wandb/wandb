package api

import (
	"context"
	"log/slog"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
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
		willRetry, err := policy(ctx, resp, err)

		if willRetry {
			switch {
			case resp == nil && err == nil:
				logger.Info("api: retrying HTTP request, no error or response")
			case err != nil:
				logger.Info("api: retrying error", "error", err)
			case resp.StatusCode >= 400:
				logger.Info(
					"api: retrying HTTP error",
					"status", resp.StatusCode,
					"url", resp.Request.URL.String(),
				)
			}
		}

		return willRetry, err
	}
}
