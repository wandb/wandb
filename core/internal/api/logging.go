package api

import (
	"bytes"
	"context"
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
				// TODO: Report the attempt number & time to next retry.
				op := wboperation.Get(ctx)
				op.MarkRetryingHTTPError(resp.Status)

				var bufferedBody bytes.Buffer
				bodyTruncated, err := io.ReadAll(
					io.LimitReader(
						io.TeeReader(resp.Body, &bufferedBody),
						1024))

				resp.Body = &closer{
					io.MultiReader(&bufferedBody, resp.Body),
					resp.Body,
				}

				var bodyStr string
				if err != nil {
					bodyStr = "error reading body"
				} else if len(bodyStr) < 1024 {
					bodyStr = string(bodyTruncated)
				} else {
					bodyStr = string(bodyTruncated[:1021]) + "..."
				}

				// TODO: Log the request body.
				logger.Info(
					"api: retrying HTTP error",
					"status", resp.StatusCode,
					"url", resp.Request.URL.String(),
					"response_body", bodyStr,
					"op", op.ToProto().Desc,
				)
			}
		}

		return willRetry, err
	}
}

type closer struct {
	io.Reader
	source io.Closer
}

func (c *closer) Close() error {
	return c.source.Close()
}
