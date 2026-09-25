package api

import (
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	traceapi "go.opentelemetry.io/otel/trace"

	"github.com/wandb/wandb/core/internal/httplayers"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// Do implements RetryableClient.Do.
func (client *clientImpl) Do(req *retryablehttp.Request) (*http.Response, error) {
	// Track retried errors to provide a better error message at the end.
	req = req.WithContext(withRetryObserver(req.Context()))

	// Start a span for this HTTP request.
	var span traceapi.Span
	if client.traceStarter != nil {
		ctx, startedSpan := client.traceStarter.StartSpan(
			httplayers.WithAttemptTracking(req.Context()),
			"wandb.core.http",
			traceapi.WithSpanKind(traceapi.SpanKindClient),
			traceapi.WithAttributes(
				attribute.String("http.request.method", req.Method),
				attribute.String("server.address", req.URL.Hostname()),
				attribute.String("url.path", req.URL.Path),
				attribute.String("operation.name", "wandb.core.http"),
				attribute.String(
					"resource.name",
					req.Method+" "+req.URL.Path,
				),
			),
		)
		req = req.WithContext(ctx)
		span = startedSpan
		defer span.End()
	}

	resp, err := client.retryableHTTP.Do(req)
	wboperation.Get(req.Context()).ClearError()

	if err != nil {
		// Record the error and status code on the span.
		if span != nil {
			span.SetAttributes(
				attribute.Int64(
					"wandb.http.attempt_count",
					httplayers.AttemptCount(req.Context()),
				),
			)
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}

		if lastStatus := lastRetriedError(req.Context()); lastStatus != "" {
			return nil, &RetryError{Inner: err, LastStatus: lastStatus}
		} else {
			return nil, err
		}
	}

	// This is a bug that happens with retryablehttp sometimes.
	if resp == nil {
		err := fmt.Errorf("api: nil error and nil response")
		if span != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}
		return nil, err
	}

	// Record the status code on the span.
	if span != nil {
		span.SetAttributes(
			attribute.Int("http.response.status_code", resp.StatusCode),
			attribute.Int64(
				"wandb.http.attempt_count",
				httplayers.AttemptCount(req.Context()),
			),
		)
		if resp.StatusCode >= http.StatusBadRequest {
			span.SetStatus(codes.Error, http.StatusText(resp.StatusCode))
		}
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}
