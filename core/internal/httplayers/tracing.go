package httplayers

import (
	"context"
	"fmt"
	"net/http"
	"sync/atomic"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	traceapi "go.opentelemetry.io/otel/trace"
)

// attemptCounterKey is the context key under which WithAttemptTracking
// stores its counter.
type attemptCounterKey struct{}

// WithAttemptTracking returns a context that TraceRequests can use to number
// the individual attempts belonging to one logical (retried) request.
//
// The same context value must be reused across all attempts of a single
// call, e.g. by passing it to a retryablehttp.Client.Do() call whose
// request/context are reused for every retry. Without this, attempt spans
// omit the wandb.http.attempt attribute, and are ambiguous.
func WithAttemptTracking(ctx context.Context) context.Context {
	return context.WithValue(ctx, attemptCounterKey{}, new(atomic.Int64))
}

// AttemptCount returns how many attempts have been recorded so far on a
// context created by WithAttemptTracking, or 0 if it wasn't set up.
func AttemptCount(ctx context.Context) int64 {
	counter, ok := ctx.Value(attemptCounterKey{}).(*atomic.Int64)
	if !ok {
		return 0
	}
	return counter.Load()
}

// TraceStarter starts spans for HTTP requests.
//
// This small interface keeps the HTTP layer independent of the analytics
// implementation.
type TraceStarter interface {
	StartSpan(
		context.Context,
		string,
		...traceapi.SpanStartOption,
	) (context.Context, traceapi.Span)
}

// TraceRequests creates a wrapper that records one client span per HTTP
// attempt. The request's query parameters are intentionally omitted (they
// may contain secrets like API keys), but its path is recorded since it's
// low-cardinality and identifies the endpoint being called.
func TraceRequests(starter TraceStarter) HTTPWrapper {
	if starter == nil {
		return nil
	}
	return traceRequests{starter: starter}
}

type traceRequests struct {
	starter TraceStarter
}

func (t traceRequests) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		attrs := []attribute.KeyValue{
			attribute.String("http.request.method", req.Method),
			attribute.String("server.address", req.URL.Hostname()),
			attribute.String("url.path", req.URL.Path),
			// Datadog's OTLP ingestion otherwise derives both the span's
			// name and its displayed "resource" by convention from span
			// kind and the semconv HTTP attributes above, which collapses
			// every span here to the operation "http.client.request" and
			// the resource "POST" -- indistinguishable from one another
			// and from the parent "wandb.core.http" span. "operation.name"
			// and "resource.name" are attribute keys Datadog specially
			// maps directly onto the span's name/resource fields instead,
			// letting us override that.
			attribute.String("operation.name", "wandb.core.http.attempt"),
			attribute.String(
				"resource.name",
				req.Method+" "+req.URL.Path,
			),
		}
		// If the caller set up attempt tracking (see WithAttemptTracking),
		// record which attempt this is so that, in a trace viewer, this
		// span isn't indistinguishable from its parent "wandb.core.http"
		// span when there happens to be exactly one attempt.
		if counter, ok := req.Context().
			Value(attemptCounterKey{}).(*atomic.Int64); ok {
			attrs = append(
				attrs,
				attribute.Int64("wandb.http.attempt", counter.Add(1)),
			)
		}

		ctx, span := t.starter.StartSpan(
			req.Context(),
			"wandb.core.http.attempt",
			traceapi.WithSpanKind(traceapi.SpanKindClient),
			traceapi.WithAttributes(attrs...),
		)
		defer span.End()

		tracedRequest := req.WithContext(ctx)
		spanContext := span.SpanContext()
		if !spanContext.IsValid() || !spanContext.IsSampled() {
			// Preserve a sampled parent when the child span is non-recording.
			// Propagation should not depend on whether this local span was
			// retained by the tracer.
			spanContext = traceapi.SpanContextFromContext(ctx)
		}
		if spanContext.IsValid() && spanContext.IsSampled() {
			tracedRequest = req.Clone(ctx)
			tracedRequest.Header.Set(
				"b3",
				fmt.Sprintf(
					"%s-%s-1",
					spanContext.TraceID(),
					spanContext.SpanID(),
				),
			)
		}

		resp, err := send(tracedRequest)
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
			return resp, err
		}

		span.SetAttributes(
			attribute.Int("http.response.status_code", resp.StatusCode),
		)
		if resp.StatusCode >= http.StatusBadRequest {
			span.SetStatus(
				codes.Error,
				http.StatusText(resp.StatusCode),
			)
		}
		return resp, nil
	}
}
