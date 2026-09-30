package api

import (
	"fmt"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"go.opentelemetry.io/otel/codes"
	traceapi "go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"

	"github.com/wandb/wandb/core/internal/wboperation"
)

// Do implements RetryableClient.Do.
func (client *clientImpl) Do(req *retryablehttp.Request) (*http.Response, error) {
	// Track retried errors to provide a better error message at the end.
	req = req.WithContext(withRetryObserver(req.Context()))

	_, span := noop.NewTracerProvider().Tracer("wandb-core/api").Start(req.Context(), "")
	if client.traceStarter != nil {
		ctx, startedSpan := client.traceStarter.StartSpan(
			req.Context(),
			fmt.Sprintf("wandb.core.http.%s", req.Method),
			traceapi.WithSpanKind(traceapi.SpanKindClient),
		)
		req = req.WithContext(ctx)
		span = startedSpan
	}
	defer func() { span.End() }()

	resp, err := client.retryableHTTP.Do(req)
	wboperation.Get(req.Context()).ClearError()

	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())

		if lastStatus := lastRetriedError(req.Context()); lastStatus != "" {
			return nil, &RetryError{Inner: err, LastStatus: lastStatus}
		} else {
			return nil, err
		}
	}

	// This is a bug that happens with retryablehttp sometimes.
	if resp == nil {
		err := fmt.Errorf("api: nil error and nil response")

		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())

		return nil, err
	}

	if resp.StatusCode >= http.StatusBadRequest {
		span.SetStatus(codes.Error, http.StatusText(resp.StatusCode))
	}

	client.logFinalResponseOnError(req, resp)
	return resp, nil
}
