//go:build linux

package monitor_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/monitor/tpuproto"
	"google.golang.org/grpc"
)

type mockRuntimeMetricServiceClient struct {
	metrics map[monitor.TPUMetricName][]*tpuproto.Metric
}

func (m *mockRuntimeMetricServiceClient) GetRuntimeMetric(ctx context.Context, in *tpuproto.MetricRequest, opts ...grpc.CallOption) (*tpuproto.MetricResponse, error) {
	metrics, ok := m.metrics[monitor.TPUMetricName(in.MetricName)]
	if !ok {
		return nil, fmt.Errorf("metric not found")
	}
	return &tpuproto.MetricResponse{
		Metric: &tpuproto.TPUMetric{
			Metrics: metrics,
		},
	}, nil
}

func TestTPUSample(t *testing.T) {
	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory: {
				{
					Attribute: &tpuproto.Attribute{
						Value: &tpuproto.AttrValue{
							Attr: &tpuproto.AttrValue_IntAttr{
								IntAttr: 0,
							},
						},
					},
					Measure: &tpuproto.Metric_Gauge{
						Gauge: &tpuproto.Gauge{
							Value: &tpuproto.Gauge_AsInt{
								AsInt: 16000000000, // 16 GiB
							},
						},
					},
				},
			},
			monitor.TPUMemoryUsage: {
				{
					Attribute: &tpuproto.Attribute{
						Value: &tpuproto.AttrValue{
							Attr: &tpuproto.AttrValue_IntAttr{
								IntAttr: 0,
							},
						},
					},
					Measure: &tpuproto.Metric_Gauge{
						Gauge: &tpuproto.Gauge{
							Value: &tpuproto.Gauge_AsInt{
								AsInt: 8000000000, // 8 GiB
							},
						},
					},
				},
			},
			monitor.TPUDutyCyclePct: {
				{
					Attribute: &tpuproto.Attribute{
						Value: &tpuproto.AttrValue{
							Attr: &tpuproto.AttrValue_IntAttr{
								IntAttr: 0,
							},
						},
					},
					Measure: &tpuproto.Metric_Gauge{
						Gauge: &tpuproto.Gauge{
							Value: &tpuproto.Gauge_AsDouble{
								AsDouble: 75.0,
							},
						},
					},
				},
			},
		},
	}

	tpu := &monitor.TPU{}
	tpu.SetName("tpu")
	tpu.SetClient(mockClient)
	tpu.SetChip(&monitor.TPUChip{
		Name:           "v42",
		HbmGiB:         16,
		DevicesPerChip: 1,
	}, 1,
	)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}
	fmt.Println(data)

	expectedMemoryUsageKey := "tpu.0.memoryUsage"
	expectedDutyCycleKey := "tpu.0.dutyCycle"

	if data[expectedMemoryUsageKey] != 50.0 {
		t.Errorf("Expected memory usage 50.0, got %v", data[expectedMemoryUsageKey])
	}

	if data[expectedDutyCycleKey] != 75.0 {
		t.Errorf("Expected duty cycle 75.0, got %v", data[expectedDutyCycleKey])
	}
}
