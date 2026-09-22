//go:build cloud_http

package filetransfer

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
)

// cloudHTTPClient retries requests without buffering their bodies. Callers
// provide GetBody for replayable uploads and authorize each fresh attempt so
// signatures and expiring credentials are not reused across retries.
type cloudHTTPClient struct {
	client      api.HTTPDoer
	authorize   func(*http.Request) error
	maxAttempts int
	retryDelay  func(attempt int, response *http.Response) time.Duration
	// retryResponse adds provider-specific error-code retries. If it reads the
	// body, it must restore it and preserve Close for the final error response.
	retryResponse func(*http.Response) bool
}

func (c *cloudHTTPClient) Do(req *http.Request) (*http.Response, error) {
	client := c.client
	if client == nil {
		client = http.DefaultClient
	}
	attempts := c.maxAttempts
	if attempts <= 0 {
		attempts = 4
	}
	// A body without a replay function must only be submitted once.
	if req.Body != nil && req.Body != http.NoBody && req.GetBody == nil {
		attempts = 1
	}

	for attempt := 0; ; attempt++ {
		current, err := c.prepareAttempt(req, attempt)
		if err != nil {
			return nil, err
		}

		resp, err := client.Do(current)
		if ctxErr := req.Context().Err(); ctxErr != nil {
			if resp != nil && resp.Body != nil {
				_ = resp.Body.Close()
			}
			return nil, ctxErr
		}
		if !c.shouldRetry(req.Context(), resp, err) || attempt+1 >= attempts {
			return resp, err
		}
		if err := c.waitForRetry(req.Context(), attempt, resp); err != nil {
			return nil, err
		}
	}
}

func (c *cloudHTTPClient) prepareAttempt(req *http.Request, attempt int) (*http.Request, error) {
	if err := req.Context().Err(); err != nil {
		if attempt == 0 && req.Body != nil {
			_ = req.Body.Close()
		}
		return nil, err
	}
	current := req.Clone(req.Context())
	if attempt > 0 && req.GetBody != nil {
		var err error
		current.Body, err = req.GetBody()
		if err != nil {
			return nil, fmt.Errorf("cloud storage: replay request: %w", err)
		}
	}
	if c.authorize != nil {
		if err := c.authorize(current); err != nil {
			if current.Body != nil {
				_ = current.Body.Close()
			}
			return nil, err
		}
	}
	return current, nil
}

func (c *cloudHTTPClient) shouldRetry(ctx context.Context, resp *http.Response, err error) bool {
	retry, _ := retryablehttp.DefaultRetryPolicy(ctx, resp, err)
	if retry || (resp != nil && resp.StatusCode == http.StatusRequestTimeout) {
		return true
	}
	return err == nil && resp != nil && c.retryResponse != nil && c.retryResponse(resp)
}

func (c *cloudHTTPClient) waitForRetry(
	ctx context.Context,
	attempt int,
	resp *http.Response,
) error {
	delay := clients.ExponentialBackoffWithJitter(
		200*time.Millisecond, 30*time.Second, attempt, resp)
	if c.retryDelay != nil {
		delay = c.retryDelay(attempt, resp)
	}
	if resp != nil && resp.Body != nil {
		// Drain small errors to permit connection reuse, but never buffer an
		// arbitrarily large error response while retrying a transfer.
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		_ = resp.Body.Close()
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// cloudResponseError consumes and closes a failed response. It deliberately
// omits the request URL, which may contain signed credentials.
func cloudResponseError(resp *http.Response) error {
	var detail string
	if resp.Body != nil {
		defer func() { _ = resp.Body.Close() }()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		detail = strings.TrimSpace(string(body))
	}
	return fmt.Errorf("cloud storage: HTTP %d %s: %s",
		resp.StatusCode, http.StatusText(resp.StatusCode), detail)
}
