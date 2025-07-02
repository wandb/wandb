//go:build linux

package monitor_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/monitor/tpuproto"
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

// Helper function to create a metric with given device ID and value
func createMetric(deviceID int64, value any) *tpuproto.Metric {
	metric := &tpuproto.Metric{
		Attribute: &tpuproto.Attribute{
			Value: &tpuproto.AttrValue{
				Attr: &tpuproto.AttrValue_IntAttr{
					IntAttr: deviceID,
				},
			},
		},
		Measure: &tpuproto.Metric_Gauge{
			Gauge: &tpuproto.Gauge{},
		},
	}

	switch v := value.(type) {
	case int64:
		metric.GetGauge().Value = &tpuproto.Gauge_AsInt{AsInt: v}
	case float64:
		metric.GetGauge().Value = &tpuproto.Gauge_AsDouble{AsDouble: v}
	}

	return metric
}

// Helper function to compare numeric values regardless of their exact type
func compareNumeric(t *testing.T, name string, got, want any) {
	switch gotVal := got.(type) {
	case int64:
		if wantVal, ok := want.(float64); ok {
			if float64(gotVal) != wantVal {
				t.Errorf("%s = %v (int64), want %v (float64)", name, gotVal, wantVal)
			}
		}
	case float64:
		if wantVal, ok := want.(float64); ok {
			if gotVal != wantVal {
				t.Errorf("%s = %v, want %v", name, gotVal, wantVal)
			}
		}
	default:
		t.Errorf("%s has unexpected type %T", name, got)
	}
}

func TestTPUSingleDeviceComplete(t *testing.T) {
	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory:  {createMetric(0, int64(16000000000))}, // 16 GiB
			monitor.TPUMemoryUsage:  {createMetric(0, int64(8000000000))},  // 8 GiB
			monitor.TPUDutyCyclePct: {createMetric(0, float64(75.0))},      // 75%
		},
	}

	tpu := &monitor.TPU{}
	tpu.SetClient(mockClient)
	tpu.SetChip(monitor.TPUChip{Name: "v4", HbmGiB: 16, DevicesPerChip: 1}, 1)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}

	metrics := make(map[string]any)
	for _, item := range data.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	expectedMetrics := map[string]float64{
		"tpu.0.memoryUsage":      50.0,
		"tpu.0.memoryUsageBytes": 8000000000,
		"tpu.0.dutyCycle":        75.0,
	}

	for key, expected := range expectedMetrics {
		if val, ok := metrics[key]; !ok {
			t.Errorf("Missing metric %s", key)
		} else {
			compareNumeric(t, key, val, expected)
		}
	}
}

func TestTPUV2MultiDevice(t *testing.T) {
	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory: {
				createMetric(0, int64(8000000000)), // Device 0: 8 GiB
				createMetric(1, int64(8000000000)), // Device 1: 8 GiB
			},
			monitor.TPUMemoryUsage: {
				createMetric(0, int64(4000000000)), // Device 0: 4 GiB
				createMetric(1, int64(2000000000)), // Device 1: 2 GiB
			},
			monitor.TPUDutyCyclePct: {
				createMetric(0, float64(80.0)), // Chip 0 (applies to both devices)
			},
		},
	}

	tpu := &monitor.TPU{}
	tpu.SetClient(mockClient)
	tpu.SetChip(monitor.TPUChip{Name: "v2", HbmGiB: 8, DevicesPerChip: 2}, 1)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}

	metrics := make(map[string]any)
	for _, item := range data.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	expectedMetrics := map[string]float64{
		"tpu.0.memoryUsage":      50.0,
		"tpu.0.memoryUsageBytes": 4000000000,
		"tpu.0.dutyCycle":        80.0,
		"tpu.1.memoryUsage":      25.0,
		"tpu.1.memoryUsageBytes": 2000000000,
		"tpu.1.dutyCycle":        80.0,
	}

	for key, expected := range expectedMetrics {
		if val, ok := metrics[key]; !ok {
			t.Errorf("Missing metric %s", key)
		} else {
			compareNumeric(t, key, val, expected)
		}
	}
}

func TestTPUPartialMetrics(t *testing.T) {
	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory: {
				createMetric(0, int64(16000000000)),
				createMetric(1, int64(16000000000)),
			},
			monitor.TPUMemoryUsage: {
				createMetric(0, int64(8000000000)),
				// Device 1 memory usage missing
			},
			monitor.TPUDutyCyclePct: {
				createMetric(0, float64(75.0)),
				createMetric(1, float64(80.0)),
			},
		},
	}

	tpu := &monitor.TPU{}
	tpu.SetClient(mockClient)
	tpu.SetChip(monitor.TPUChip{Name: "v4", HbmGiB: 16, DevicesPerChip: 1}, 2)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}

	metrics := make(map[string]any)
	for _, item := range data.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	expectedMetrics := map[string]float64{
		"tpu.0.memoryUsage":      50.0,
		"tpu.0.memoryUsageBytes": 8000000000,
		"tpu.0.dutyCycle":        75.0,
		"tpu.1.dutyCycle":        80.0,
	}

	for key, expected := range expectedMetrics {
		if val, ok := metrics[key]; !ok {
			t.Errorf("Missing metric %s", key)
		} else {
			compareNumeric(t, key, val, expected)
		}
	}

	// Verify memory metrics for device 1 are missing
	if _, exists := metrics["tpu.1.memoryUsage"]; exists {
		t.Error("tpu.1.memoryUsage should not exist")
	}
	if _, exists := metrics["tpu.1.memoryUsageBytes"]; exists {
		t.Error("tpu.1.memoryUsageBytes should not exist")
	}
}

func TestTPUNonSequentialDeviceIDs(t *testing.T) {
	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory: {
				createMetric(42, int64(16000000000)),
				createMetric(46, int64(16000000000)),
			},
			monitor.TPUMemoryUsage: {
				createMetric(42, int64(8000000000)),
				createMetric(46, int64(4000000000)),
			},
			monitor.TPUDutyCyclePct: {
				createMetric(42, float64(75.0)),
				createMetric(46, float64(80.0)),
			},
		},
	}

	tpu := &monitor.TPU{}
	tpu.SetClient(mockClient)
	tpu.SetChip(monitor.TPUChip{Name: "v4", HbmGiB: 16, DevicesPerChip: 1}, 2)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}

	metrics := make(map[string]any)
	for _, item := range data.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	expectedMetrics := map[string]float64{
		"tpu.42.memoryUsage":      50.0,
		"tpu.42.memoryUsageBytes": 8000000000,
		"tpu.42.dutyCycle":        75.0,
		"tpu.46.memoryUsage":      25.0,
		"tpu.46.memoryUsageBytes": 4000000000,
		"tpu.46.dutyCycle":        80.0,
	}

	for key, expected := range expectedMetrics {
		if val, ok := metrics[key]; !ok {
			t.Errorf("Missing metric %s", key)
		} else {
			compareNumeric(t, key, val, expected)
		}
	}
}
