//go:build linux

package monitor_test

import (
	"context"
	"fmt"
	"testing"

	"github.com/wandb/simplejsonext"
	"google.golang.org/grpc"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/monitor/tpuproto"
)

type mockRuntimeMetricServiceClient struct {
	metrics map[monitor.TPUMetricName][]*tpuproto.Metric
}

func (m *mockRuntimeMetricServiceClient) GetRuntimeMetric(
	ctx context.Context,
	in *tpuproto.MetricRequest,
	opts ...grpc.CallOption,
) (*tpuproto.MetricResponse, error) {
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

func (m *mockRuntimeMetricServiceClient) ListSupportedMetrics(
	ctx context.Context,
	in *tpuproto.ListSupportedMetricsRequest,
	opts ...grpc.CallOption,
) (*tpuproto.ListSupportedMetricsResponse, error) {
	supported := []*tpuproto.SupportedMetric{
		{MetricName: string(monitor.TPUTotalMemory)},
		{MetricName: string(monitor.TPUMemoryUsage)},
		{MetricName: string(monitor.TPUDutyCyclePct)},
	}
	// Include all registered metric names so distribution tests work.
	for name := range m.metrics {
		supported = append(supported, &tpuproto.SupportedMetric{MetricName: string(name)})
	}
	return &tpuproto.ListSupportedMetricsResponse{SupportedMetric: supported}, nil
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

func TestTPUDistributionMetrics(t *testing.T) {
	const bufferTransferMetric = "megascale.dcn_transfer_latencies.microsecond.cumulative.distribution"
	const grpcMinRttMetric = "megascale.grpc_tcp_min_rtt.microsecond.cumulative.distribution"

	mockClient := &mockRuntimeMetricServiceClient{
		metrics: map[monitor.TPUMetricName][]*tpuproto.Metric{
			monitor.TPUTotalMemory:  {createMetric(0, int64(16000000000))},
			monitor.TPUMemoryUsage:  {createMetric(0, int64(8000000000))},
			monitor.TPUDutyCyclePct: {createMetric(0, float64(75.0))},
			monitor.TPUMetricName(bufferTransferMetric): {
				{
					Attribute: &tpuproto.Attribute{
						Key: "label",
						Value: &tpuproto.AttrValue{
							Attr: &tpuproto.AttrValue_StringAttr{StringAttr: "slice_0"},
						},
					},
					Measure: &tpuproto.Metric_Distribution{
						Distribution: &tpuproto.Distribution{
							Count: 1000,
							Mean:  50.0,
							Min:   10.0,
							Max:   200.0,
							BucketOptions: &tpuproto.Distribution_BucketOptions{
								Options: &tpuproto.Distribution_BucketOptions_ExponentialBuckets{
									ExponentialBuckets: &tpuproto.Distribution_BucketOptions_Exponential{
										NumFiniteBuckets: 4,
										GrowthFactor:     2.0,
										Scale:            10.0,
									},
								},
							},
							// Buckets: [0,10), [10,20), [20,40), [40,80), [80,160), [160,+inf)
							// Counts:    0      100      300      400      150        50
							BucketCounts: []int64{0, 100, 300, 400, 150, 50},
						},
					},
				},
			},
			monitor.TPUMetricName(grpcMinRttMetric): {
				{
					Attribute: &tpuproto.Attribute{
						Key: "instance",
						Value: &tpuproto.AttrValue{
							Attr: &tpuproto.AttrValue_StringAttr{StringAttr: "rtt_0"},
						},
					},
					Measure: &tpuproto.Metric_Summary{
						Summary: &tpuproto.Summary{
							SampleCount: 500,
							SampleSum:   25000.0,
							Quantile: []*tpuproto.Quantile{
								{Quantile: 0.50, Value: 42.0},
								{Quantile: 0.90, Value: 88.0},
								{Quantile: 0.95, Value: 95.0},
								{Quantile: 0.999, Value: 150.0},
							},
						},
					},
				},
			},
		},
	}

	// Update mock to include distribution metrics in supported list.
	origList := mockClient.ListSupportedMetrics
	_ = origList
	tpu := &monitor.TPU{}
	tpu.SetClient(mockClient)
	tpu.SetChip(monitor.TPUChip{Name: "v5e", HbmGiB: 16, DevicesPerChip: 1}, 1)

	data, err := tpu.Sample()
	if err != nil {
		t.Fatalf("Sample() error = %v", err)
	}

	metrics := make(map[string]any)
	for _, item := range data.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	// Verify basic metrics still work.
	if val, ok := metrics["tpu.0.dutyCycle"]; !ok {
		t.Error("Missing tpu.0.dutyCycle")
	} else {
		compareNumeric(t, "tpu.0.dutyCycle", val, 75.0)
	}

	// Verify distribution percentiles are computed.
	if val, ok := metrics["tpu.bufferTransferLatency.slice_0.meanUs"]; !ok {
		t.Error("Missing tpu.bufferTransferLatency.slice_0.meanUs")
	} else {
		compareNumeric(t, "tpu.bufferTransferLatency.slice_0.meanUs", val, 50.0)
	}

	// p50 should be in the [20,40) bucket (cumulative at 400 = 40% by bucket index 2).
	if _, ok := metrics["tpu.bufferTransferLatency.slice_0.p50Us"]; !ok {
		t.Error("Missing tpu.bufferTransferLatency.slice_0.p50Us")
	}

	// Verify summary-based metric (grpc min RTT).
	if val, ok := metrics["tpu.grpcTcpMinRtt.rtt_0.meanUs"]; !ok {
		t.Error("Missing tpu.grpcTcpMinRtt.rtt_0.meanUs")
	} else {
		compareNumeric(t, "tpu.grpcTcpMinRtt.rtt_0.meanUs", val, 50.0) // 25000/500
	}
	if val, ok := metrics["tpu.grpcTcpMinRtt.rtt_0.p50Us"]; !ok {
		t.Error("Missing tpu.grpcTcpMinRtt.rtt_0.p50Us")
	} else {
		compareNumeric(t, "tpu.grpcTcpMinRtt.rtt_0.p50Us", val, 42.0)
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
