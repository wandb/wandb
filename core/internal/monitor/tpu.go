//go:build linux

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/monitor/tpuproto"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TPUMetricName represents a TPU runtime metric name exposed by the local
// runtime gRPC server.
type TPUMetricName string

const (
	// googleTPUVendorID is the PCI vendor ID assigned to Google TPUs.
	googleTPUVendorID = "0x1ae0"

	// grpcAddr is the TPU runtime metric service endpoint.
	grpcAddr = "localhost:8431"

	defaultTPUSampleTimeout = 5 * time.Second

	// Stable runtime metrics. Additional runtime metrics are discovered via
	// ListSupportedMetrics and sampled opportunistically.
	TPUTotalMemory  TPUMetricName = "tpu.runtime.hbm.memory.total.bytes"
	TPUMemoryUsage  TPUMetricName = "tpu.runtime.hbm.memory.usage.bytes"
	TPUDutyCyclePct TPUMetricName = "tpu.runtime.tensorcore.dutycycle.percent"
)

// TPUChip represents TPU chip specifications.
type TPUChip struct {
	Name           string
	HbmGiB         int
	DevicesPerChip int
}

type RuntimeMetricServiceClient interface {
	GetRuntimeMetric(
		ctx context.Context,
		in *tpuproto.MetricRequest,
		opts ...grpc.CallOption,
	) (*tpuproto.MetricResponse, error)
	ListSupportedMetrics(
		ctx context.Context,
		in *tpuproto.ListSupportedMetricsRequest,
		opts ...grpc.CallOption,
	) (*tpuproto.ListSupportedMetricsResponse, error)
}

type runtimeMetricSelection struct {
	Supported             []string
	TotalMemory           string
	MemoryUsage           string
	DutyCycle             string
	TensorcoreUtilization string
	MemoryBandwidthUtil   string
	HLOExecutionTiming    string
	HLOQueueSize          string
}

// TPU collects TPU metrics from two backends:
//   - the local runtime gRPC service on localhost:8431
//   - libtpu.so, loaded directly with purego for metrics only available there
//
// Runtime metrics win on duplicate keys.
type TPU struct {
	conn   *grpc.ClientConn
	client RuntimeMetricServiceClient

	chip  TPUChip
	count int

	logger        *observability.CoreLogger
	sampleTimeout time.Duration

	runtimeMu             sync.Mutex
	runtimeMetricNames    runtimeMetricSelection
	runtimeMetricNamesSet bool

	libtpu libtpuCollector
}

// NewTPU creates a TPU collector when a local TPU is present.
func NewTPU(logger *observability.CoreLogger) *TPU {
	chip, count := getLocalTPUChips()
	if count == 0 {
		return nil
	}

	t := &TPU{
		chip:          chip,
		count:         count,
		logger:        logger,
		sampleTimeout: defaultTPUSampleTimeout,
	}

	if conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(local.NewCredentials())); err == nil {
		t.conn = conn
		t.client = tpuproto.NewRuntimeMetricServiceClient(conn)
	} else if logger != nil {
		logger.Debug("tpu: failed to initialize runtime gRPC client", "error", err)
	}

	if collector, err := newLibtpuCollector(logger); err == nil {
		t.libtpu = collector
	} else if logger != nil {
		logger.Debug("tpu: failed to initialize direct libtpu collector", "error", err)
	}

	if t.client == nil && t.libtpu == nil {
		return nil
	}
	return t
}

func (t *TPU) SetChip(chip TPUChip, count int) {
	t.chip = chip
	t.count = count
}

func (t *TPU) SetClient(client RuntimeMetricServiceClient) {
	t.client = client
}

// Sample returns TPU metrics from the runtime gRPC service and libtpu.so.
func (t *TPU) Sample() (*spb.StatsRecord, error) {
	if t.client == nil && t.libtpu == nil {
		return nil, fmt.Errorf("TPU metrics backends are unavailable")
	}

	ctx, cancel := context.WithTimeout(context.Background(), t.sampleTimeout)
	defer cancel()

	var runtimeMetrics map[string]any
	var runtimeErr error
	var libtpuMetrics map[string]any
	var libtpuErr error

	var wg sync.WaitGroup
	if t.client != nil {
		wg.Go(func() {
			runtimeMetrics, runtimeErr = t.sampleRuntime(ctx)
		})
	}
	if t.libtpu != nil {
		wg.Go(func() {
			libtpuMetrics, libtpuErr = t.libtpu.Sample(ctx)
		})
	}
	wg.Wait()

	merged := make(map[string]any)
	for k, v := range libtpuMetrics {
		merged[k] = v
	}
	for k, v := range runtimeMetrics {
		merged[k] = v
	}

	if len(merged) == 0 {
		return nil, errors.Join(runtimeErr, libtpuErr)
	}
	return marshal(merged, timestamppb.Now()), errors.Join(runtimeErr, libtpuErr)
}

func (t *TPU) sampleRuntime(ctx context.Context) (map[string]any, error) {
	selection := t.ensureRuntimeMetricSelection(ctx)

	requested := map[string]string{
		"total_memory": selection.TotalMemory,
		"memory_usage": selection.MemoryUsage,
		"duty_cycle":   selection.DutyCycle,
	}
	if selection.TensorcoreUtilization != "" {
		requested["tensorcore_utilization"] = selection.TensorcoreUtilization
	}
	if selection.MemoryBandwidthUtil != "" {
		requested["memory_bandwidth_utilization"] = selection.MemoryBandwidthUtil
	}
	if selection.HLOExecutionTiming != "" {
		requested["hlo_exec_timing"] = selection.HLOExecutionTiming
	}
	if selection.HLOQueueSize != "" {
		requested["hlo_queue_size"] = selection.HLOQueueSize
	}

	metricSets, err := t.queryRuntimeMetricSets(ctx, requested)
	metrics := t.runtimeMetricSetsToStats(metricSets)
	if len(metrics) == 0 {
		return nil, err
	}
	return metrics, err
}

func (t *TPU) ensureRuntimeMetricSelection(ctx context.Context) runtimeMetricSelection {
	t.runtimeMu.Lock()
	if t.runtimeMetricNamesSet {
		selection := withRuntimeMetricDefaults(t.runtimeMetricNames)
		t.runtimeMu.Unlock()
		return selection
	}
	t.runtimeMu.Unlock()

	selection := withRuntimeMetricDefaults(runtimeMetricSelection{})
	if t.client == nil {
		return selection
	}

	resp, err := t.client.ListSupportedMetrics(ctx, &tpuproto.ListSupportedMetricsRequest{})
	if err != nil {
		return selection
	}

	supported := make([]string, 0, len(resp.SupportedMetric))
	for _, metric := range resp.SupportedMetric {
		name := strings.TrimSpace(metric.GetMetricName())
		if name != "" {
			supported = append(supported, name)
		}
	}
	sort.Strings(supported)
	selection.Supported = supported

	for _, name := range supported {
		normalized := normalizeMetricName(name)
		switch {
		case hasAllTokens(normalized, "hbm", "memory", "total", "bytes"):
			selection.TotalMemory = name
		case hasAllTokens(normalized, "hbm", "memory", "usage", "bytes"):
			selection.MemoryUsage = name
		case hasAllTokens(normalized, "tensorcore") && hasAnyToken(normalized, "dutycycle", "duty", "duty cycle"):
			selection.DutyCycle = name
		case hasAllTokens(normalized, "tensorcore") && hasAnyToken(normalized, "util", "utilization") &&
			!hasAnyToken(normalized, "dutycycle", "duty", "duty cycle"):
			selection.TensorcoreUtilization = name
		case hasAllTokens(normalized, "bandwidth") && hasAnyToken(normalized, "memory", "hbm") && hasAnyToken(normalized, "util", "utilization"):
			selection.MemoryBandwidthUtil = name
		case hasAllTokens(normalized, "hlo", "queue", "size"):
			selection.HLOQueueSize = name
		case hasAllTokens(normalized, "hlo") && hasAnyToken(normalized, "exec", "execution") && hasAnyToken(normalized, "timing", "duration", "time"):
			selection.HLOExecutionTiming = name
		}
	}

	t.runtimeMu.Lock()
	if !t.runtimeMetricNamesSet {
		t.runtimeMetricNames = selection
		t.runtimeMetricNamesSet = true
	}
	selection = withRuntimeMetricDefaults(t.runtimeMetricNames)
	t.runtimeMu.Unlock()
	return selection
}

func withRuntimeMetricDefaults(selection runtimeMetricSelection) runtimeMetricSelection {
	if selection.TotalMemory == "" {
		selection.TotalMemory = string(TPUTotalMemory)
	}
	if selection.MemoryUsage == "" {
		selection.MemoryUsage = string(TPUMemoryUsage)
	}
	if selection.DutyCycle == "" {
		selection.DutyCycle = string(TPUDutyCyclePct)
	}
	return selection
}

func normalizeMetricName(name string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(name) {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		default:
			b.WriteByte(' ')
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

func hasAllTokens(name string, tokens ...string) bool {
	for _, token := range tokens {
		if !strings.Contains(name, token) {
			return false
		}
	}
	return true
}

func hasAnyToken(name string, tokens ...string) bool {
	for _, token := range tokens {
		if strings.Contains(name, token) {
			return true
		}
	}
	return false
}

func (t *TPU) queryRuntimeMetricSets(ctx context.Context, requested map[string]string) (map[string][]*tpuproto.Metric, error) {
	results := make(map[string][]*tpuproto.Metric, len(requested))
	var mu sync.Mutex
	var errMu sync.Mutex
	var errs []error

	var wg sync.WaitGroup
	for logicalName, runtimeMetricName := range requested {
		logicalName := logicalName
		runtimeMetricName := runtimeMetricName
		if runtimeMetricName == "" {
			continue
		}

		wg.Go(func() {
			metrics, err := t.getMetrics(ctx, TPUMetricName(runtimeMetricName))
			if err != nil {
				errMu.Lock()
				errs = append(errs, fmt.Errorf("%s: %w", logicalName, err))
				errMu.Unlock()
				return
			}
			mu.Lock()
			results[logicalName] = metrics
			mu.Unlock()
		})
	}
	wg.Wait()
	return results, errors.Join(errs...)
}

func (t *TPU) runtimeMetricSetsToStats(metricSets map[string][]*tpuproto.Metric) map[string]any {
	metrics := make(map[string]any)

	totalMemories := parseIntGaugeByDevice(metricSets["total_memory"])
	memoryUsages := parseIntGaugeByDevice(metricSets["memory_usage"])
	dutyCycles := t.parseRuntimeDutyCycles(metricSets["duty_cycle"])
	tensorcoreUtils := parseFloatGaugeByDevice(metricSets["tensorcore_utilization"])
	memoryBandwidthUtils := parseFloatGaugeByDevice(metricSets["memory_bandwidth_utilization"])

	deviceIDs := make(map[int64]struct{})
	for _, ids := range []map[int64]int64{totalMemories, memoryUsages} {
		for id := range ids {
			deviceIDs[id] = struct{}{}
		}
	}
	for _, ids := range []map[int64]float64{dutyCycles, tensorcoreUtils, memoryBandwidthUtils} {
		for id := range ids {
			deviceIDs[id] = struct{}{}
		}
	}

	for deviceID := range deviceIDs {
		if memoryUsage, ok := memoryUsages[deviceID]; ok {
			metrics[fmt.Sprintf("tpu.%d.memoryUsageBytes", deviceID)] = memoryUsage
			if totalMemory, ok := totalMemories[deviceID]; ok && totalMemory > 0 {
				metrics[fmt.Sprintf("tpu.%d.memoryUsage", deviceID)] = float64(memoryUsage) / float64(totalMemory) * 100
			}
		}
		if dutyCycle, ok := dutyCycles[deviceID]; ok {
			metrics[fmt.Sprintf("tpu.%d.dutyCycle", deviceID)] = dutyCycle
		}
		if utilization, ok := tensorcoreUtils[deviceID]; ok {
			metrics[fmt.Sprintf("tpu.%d.tensorcoreUtilization", deviceID)] = utilization
		}
		if utilization, ok := memoryBandwidthUtils[deviceID]; ok {
			metrics[fmt.Sprintf("tpu.%d.memoryBandwidthUtilization", deviceID)] = utilization
		}
	}

	appendRuntimeHLOExecutionTiming(metrics, metricSets["hlo_exec_timing"])
	appendRuntimeHLOQueueSize(metrics, metricSets["hlo_queue_size"])
	return metrics
}

func parseIntGaugeByDevice(metricSet []*tpuproto.Metric) map[int64]int64 {
	values := make(map[int64]int64, len(metricSet))
	for _, metric := range metricSet {
		deviceID, ok := metricDeviceID(metric)
		if !ok || metric.GetGauge() == nil {
			continue
		}
		values[deviceID] = metric.GetGauge().GetAsInt()
	}
	return values
}

func parseFloatGaugeByDevice(metricSet []*tpuproto.Metric) map[int64]float64 {
	values := make(map[int64]float64, len(metricSet))
	for _, metric := range metricSet {
		deviceID, ok := metricDeviceID(metric)
		if !ok || metric.GetGauge() == nil {
			continue
		}
		value := metric.GetGauge().GetAsDouble()
		if value == 0 && metric.GetGauge().GetAsInt() != 0 {
			value = float64(metric.GetGauge().GetAsInt())
		}
		values[deviceID] = value
	}
	return values
}

func metricDeviceID(metric *tpuproto.Metric) (int64, bool) {
	if metric == nil || metric.GetAttribute() == nil || metric.GetAttribute().GetValue() == nil {
		return 0, false
	}
	return metric.GetAttribute().GetValue().GetIntAttr(), true
}

func (t *TPU) parseRuntimeDutyCycles(metricSet []*tpuproto.Metric) map[int64]float64 {
	values := make(map[int64]float64, len(metricSet))
	for _, metric := range metricSet {
		deviceID, ok := metricDeviceID(metric)
		if !ok || metric.GetGauge() == nil {
			continue
		}
		dutyCycle := metric.GetGauge().GetAsDouble()
		if t.chip.DevicesPerChip == 2 {
			values[deviceID*2] = dutyCycle
			values[deviceID*2+1] = dutyCycle
		} else {
			values[deviceID] = dutyCycle
		}
	}
	return values
}

func appendRuntimeHLOExecutionTiming(out map[string]any, metricSet []*tpuproto.Metric) {
	for idx, metric := range metricSet {
		label := runtimeMetricLabel(metric, fmt.Sprintf("item_%d", idx))
		if summary := metric.GetSummary(); summary != nil {
			if count := summary.GetSampleCount(); count > 0 {
				out[fmt.Sprintf("tpu.hloExecTiming.%s.meanUs", label)] = summary.GetSampleSum() / float64(count)
			}
			for _, q := range summary.GetQuantile() {
				name := quantileName(q.GetQuantile())
				if name == "" {
					continue
				}
				out[fmt.Sprintf("tpu.hloExecTiming.%s.%sUs", label, name)] = q.GetValue()
			}
			continue
		}
		if distribution := metric.GetDistribution(); distribution != nil && distribution.GetCount() > 0 {
			out[fmt.Sprintf("tpu.hloExecTiming.%s.meanUs", label)] = distribution.GetMean()
			continue
		}
		if gauge := metric.GetGauge(); gauge != nil {
			value := gauge.GetAsDouble()
			if value == 0 && gauge.GetAsInt() != 0 {
				value = float64(gauge.GetAsInt())
			}
			out[fmt.Sprintf("tpu.hloExecTiming.%s.meanUs", label)] = value
		}
	}
}

func appendRuntimeHLOQueueSize(out map[string]any, metricSet []*tpuproto.Metric) {
	for idx, metric := range metricSet {
		if metric.GetGauge() == nil {
			continue
		}
		label := runtimeMetricLabel(metric, fmt.Sprintf("item_%d", idx))
		value := metric.GetGauge().GetAsInt()
		if value == 0 && metric.GetGauge().GetAsDouble() != 0 {
			out[fmt.Sprintf("tpu.hloQueueSize.%s", label)] = metric.GetGauge().GetAsDouble()
			continue
		}
		out[fmt.Sprintf("tpu.hloQueueSize.%s", label)] = value
	}
}

func runtimeMetricLabel(metric *tpuproto.Metric, fallback string) string {
	if metric == nil || metric.GetAttribute() == nil || metric.GetAttribute().GetValue() == nil {
		return fallback
	}
	if value := strings.TrimSpace(metric.GetAttribute().GetValue().GetStringAttr()); value != "" {
		return sanitizeMetricLabel(value)
	}
	return fallback
}

func quantileName(q float64) string {
	switch {
	case almostEqual(q, 0.50):
		return "p50"
	case almostEqual(q, 0.90):
		return "p90"
	case almostEqual(q, 0.95):
		return "p95"
	case almostEqual(q, 0.99):
		return "p99"
	case almostEqual(q, 0.999):
		return "p999"
	default:
		return ""
	}
}

func almostEqual(a, b float64) bool {
	const epsilon = 1e-9
	if a > b {
		return a-b < epsilon
	}
	return b-a < epsilon
}

// Close closes the gRPC connection and the libtpu handle.
func (t *TPU) Close() {
	if t.conn != nil {
		_ = t.conn.Close()
		t.conn = nil
		t.client = nil
	}
	if t.libtpu != nil {
		_ = t.libtpu.Close()
		t.libtpu = nil
	}
}

// Probe returns TPU metadata and logs detected runtime/libtpu capabilities.
func (t *TPU) Probe(ctx context.Context) *spb.EnvironmentRecord {
	if t.count == 0 {
		return nil
	}

	if t.client != nil {
		if resp, err := t.client.ListSupportedMetrics(ctx, &tpuproto.ListSupportedMetricsRequest{}); err == nil {
			supportedMetrics := make([]string, 0, len(resp.SupportedMetric))
			for _, sm := range resp.SupportedMetric {
				supportedMetrics = append(supportedMetrics, sm.MetricName)
			}
			sort.Strings(supportedMetrics)
			t.logger.Debug("tpu: supported runtime metrics", "metrics", supportedMetrics)
		}
	}

	if t.libtpu != nil {
		if probe, err := t.libtpu.Probe(ctx); err == nil {
			t.logger.Debug(
				"tpu: direct libtpu monitoring ready",
				"path", probe.LibraryPath,
				"version", probe.Version,
				"metrics", probe.SupportedMetrics,
				"symbols", probe.Symbols,
			)
		}
	}

	return &spb.EnvironmentRecord{
		Tpu: &spb.TPUInfo{
			Name:           t.chip.Name,
			Count:          uint32(t.count),
			HbmGib:         uint32(t.chip.HbmGiB),
			DevicesPerChip: uint32(t.chip.DevicesPerChip),
		},
	}
}

// getLocalTPUChips scans the PCI devices to detect local TPU chips and
// returns the most common chip type and the total count.
func getLocalTPUChips() (TPUChip, int) { //nolint
	devices, err := filepath.Glob("/sys/bus/pci/devices/*")
	if err != nil {
		return TPUChip{}, 0
	}

	counter := make(map[TPUChip]int)

	for _, pciPath := range devices {
		vendorPath := filepath.Join(pciPath, "vendor")
		data, err := os.ReadFile(vendorPath)
		if err != nil {
			continue
		}
		vendorID := strings.TrimSpace(string(data))
		if vendorID != googleTPUVendorID {
			continue
		}

		devicePath := filepath.Join(pciPath, "device")
		data, err = os.ReadFile(devicePath)
		if err != nil {
			continue
		}
		deviceID := strings.TrimSpace(string(data))

		subsystemPath := filepath.Join(pciPath, "subsystem_device")
		data, err = os.ReadFile(subsystemPath)
		if err != nil {
			continue
		}
		subsystemID := strings.TrimSpace(string(data))

		chipType, err := tpuChipFromPCIDeviceID(deviceID, subsystemID)
		if err != nil {
			continue
		}

		counter[chipType]++
	}

	if len(counter) == 0 {
		return TPUChip{}, 0
	}

	var mostCommonChip TPUChip
	var maxCount int
	for chip, count := range counter {
		if count > maxCount {
			mostCommonChip = chip
			maxCount = count
		}
	}
	return mostCommonChip, maxCount
}

func tpuChipFromPCIDeviceID(deviceID, subsystemID string) (TPUChip, error) {
	switch deviceID {
	case "0x0027":
		switch subsystemID {
		case "0x004e":
			return TPUChip{Name: "v2", HbmGiB: 8, DevicesPerChip: 2}, nil
		case "0x004f":
			return TPUChip{Name: "v3", HbmGiB: 16, DevicesPerChip: 2}, nil
		}
	case "0x005e":
		return TPUChip{Name: "v4", HbmGiB: 32, DevicesPerChip: 1}, nil
	case "0x0063":
		return TPUChip{Name: "v5e", HbmGiB: 16, DevicesPerChip: 1}, nil
	case "0x0062":
		return TPUChip{Name: "v5p", HbmGiB: 95, DevicesPerChip: 1}, nil
	case "0x006f":
		return TPUChip{Name: "v6e", HbmGiB: 32, DevicesPerChip: 1}, nil
	case "0x0076":
		return TPUChip{Name: "7x", HbmGiB: 192, DevicesPerChip: 2}, nil
	}

	return TPUChip{}, fmt.Errorf("unknown TPU chip")
}

// getMetrics retrieves metrics from the TPU runtime gRPC service.
func (t *TPU) getMetrics(
	ctx context.Context,
	metricName TPUMetricName,
) ([]*tpuproto.Metric, error) {
	req := &tpuproto.MetricRequest{MetricName: string(metricName)}
	resp, err := t.client.GetRuntimeMetric(ctx, req)
	if err != nil {
		return nil, err
	}
	return resp.Metric.Metrics, nil
}
