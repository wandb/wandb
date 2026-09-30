package httplayers_test

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	traceapi "go.opentelemetry.io/otel/trace"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	. "github.com/wandb/wandb/core/internal/httplayers"
)

func TestTraceRequestsRecordsRedactedHTTPAttempt(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)
	traceID, err := traceapi.TraceIDFromHex("11111111111111111111111111111111")
	require.NoError(t, err)
	parentSpanID, err := traceapi.SpanIDFromHex("1111111111111111")
	require.NoError(t, err)
	parent := traceapi.NewSpanContext(traceapi.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     parentSpanID,
		TraceFlags: traceapi.FlagsSampled,
		Remote:     true,
	})

	request, err := http.NewRequestWithContext(
		traceapi.ContextWithRemoteSpanContext(context.Background(), parent),
		http.MethodPost,
		"https://api.example.com/graphql?api_key=secret",
		http.NoBody,
	)
	require.NoError(t, err)

	var b3Header string
	send := TraceRequests(recorder).WrapHTTP(func(req *http.Request) (*http.Response, error) {
		b3Header = req.Header.Get("b3")
		return &http.Response{
			StatusCode: http.StatusOK,
			Body:       io.NopCloser(strings.NewReader("")),
			Request:    req,
		}, nil
	})
	_, err = send(request)
	require.NoError(t, err)

	require.NoError(t, proxy.Shutdown(context.Background()))
	recordedSpan, ok := proxy.FindSpan("wandb.core.http.attempt")
	require.True(t, ok, "expected an HTTP attempt span")
	assert.Equal(t, traceID, recordedSpan.TraceID)
	assert.Equal(t, parentSpanID, recordedSpan.ParentSpanID)
	assert.Equal(t, "POST", recordedSpan.Attributes["http.request.method"])
	assert.Equal(t, "api.example.com", recordedSpan.Attributes["server.address"])
	assert.Equal(t, "/graphql", recordedSpan.Attributes["url.path"])
	assert.NotContains(t, recordedSpan.Attributes, "http.url")
	assert.Equal(
		t,
		recordedSpan.TraceID.String()+"-"+recordedSpan.SpanID.String()+"-1",
		b3Header,
	)
}
