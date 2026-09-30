package httplayers

import (
	"context"
	"fmt"
	"net/http"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	traceapi "go.opentelemetry.io/otel/trace"
)

// TraceStarter starts spans for HTTP requests.
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
		ctx, span := t.starter.StartSpan(
			req.Context(),
			"wandb.core.http.attempt",
			traceapi.WithSpanKind(traceapi.SpanKindClient),
			traceapi.WithAttributes(
				attribute.String("http.request.method", req.Method),
				attribute.String("server.address", req.URL.Hostname()),
				attribute.String("url.path", req.URL.Path),
			),
		)
		defer span.End()

		tracedRequest := req.WithContext(ctx)
		spanContext := span.SpanContext()
		if spanContext.IsValid() && spanContext.IsSampled() {
			tracedRequest = req.Clone(ctx)

			// Add B3 header so this span can be correlated with spans on the backend.
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
