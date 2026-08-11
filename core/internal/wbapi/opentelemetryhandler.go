package wbapi

import (
	"context"
	"fmt"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	otellogapi "go.opentelemetry.io/otel/log"
)

type OpenTelemetryHandler struct {
	otelProvider      *analytics.OpenTelemetryProxy
	telemetryRecorder *analytics.TelemetryRecorder
}

func NewOpenTelemetryHandler(s *settings.Settings, serviceName string) *OpenTelemetryHandler {
	otelProvider := analytics.NewOpenTelemetryProxy(
		context.Background(),
		s,
		serviceName,
	)
	telemetryRecorder := analytics.NewTelemetryRecorder(
		otelProvider,
		analytics.TelemetryContext{},
	)

	return &OpenTelemetryHandler{
		otelProvider:      otelProvider,
		telemetryRecorder: telemetryRecorder,
	}
}

func (h *OpenTelemetryHandler) HandleRequest(
	ctx context.Context,
	request *spb.OpenTelemetryRequest,
) *spb.ApiResponse {
	switch req := request.Request.(type) {
	case *spb.OpenTelemetryRequest_OpenTelemetryLogRequest:
		h.Log(ctx, req.OpenTelemetryLogRequest)
		return nil // no response
	case *spb.OpenTelemetryRequest_OpenTelemetryCounterRequest:
		h.IncrementCounter(ctx, req.OpenTelemetryCounterRequest)
		return nil // no response
	default:
		return apiErrorResponse(fmt.Sprintf("unsupported API request type: %T", request.Request), 0)
	}
}

func (h *OpenTelemetryHandler) Log(
	ctx context.Context,
	request *spb.OpenTelemetryLogRequest,
) {
	h.telemetryRecorder.Log(
		ctx,
		request.Message,
		request.Attributes,
		otellogapi.Severity(request.Severity),
	)
}

func (h *OpenTelemetryHandler) IncrementCounter(
	ctx context.Context,
	request *spb.OpenTelemetryCounterRequest,
) {
	var lowCardinalityAttributes analytics.LowCardinalityAttributes
	if protoAttrs := request.GetLowCardinalityAttributes(); protoAttrs != nil {
		lowCardinalityAttributes = analytics.LowCardinalityAttributes{
			PythonVersion: protoAttrs.GetPythonVersion(),
			PythonRuntime: protoAttrs.GetPythonRuntime(),
			WandbVersion:  protoAttrs.GetWandbVersion(),
			ExceptionType: protoAttrs.GetExceptionType(),
		}
	}

	h.telemetryRecorder.IncrementCounter(
		ctx,
		request.Name,
		lowCardinalityAttributes,
	)
}

func (h *OpenTelemetryHandler) Shutdown(ctx context.Context) error {
	return h.otelProvider.Shutdown(ctx)
}
