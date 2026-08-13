package wbapi

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestOpenTelemetryHandlerRecordsOptionalCounterAttributes(t *testing.T) {
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	handler := &OpenTelemetryHandler{
		otelProvider: proxy.OpenTelemetryProxy,
		telemetryRecorder: analytics.NewTelemetryRecorder(
			proxy.OpenTelemetryProxy,
			analytics.NewTelemetryContext(),
		),
	}

	response := handler.HandleRequest(
		t.Context(),
		&spb.OpenTelemetryRequest{
			Request: &spb.OpenTelemetryRequest_OpenTelemetryCounterRequest{
				OpenTelemetryCounterRequest: &spb.OpenTelemetryCounterRequest{
					Name: "python_counter",
					LowCardinalityAttributes: &spb.LowCardinalityAttributes{
						PythonVersion: proto.String("3.13.0"),
						ExceptionType: proto.String("ValueError"),
					},
				},
			},
		},
	)
	assert.Nil(t, response)
	require.NoError(t, handler.Shutdown(context.Background()))

	metric, ok := proxy.FindMetric("python_counter")
	require.True(t, ok, "expected a metric for the counter request")
	assert.Equal(t, "3.13.0", metric.Attributes["python_version"])
	assert.Equal(t, "ValueError", metric.Attributes["exception_type"])
	assert.NotContains(t, metric.Attributes, "python_runtime")
}
