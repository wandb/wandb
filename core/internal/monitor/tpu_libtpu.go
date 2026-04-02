//go:build linux

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"unsafe"

	"github.com/ebitengine/purego"

	"github.com/wandb/wandb/core/internal/observability"
)

// Environment overrides for direct libtpu integration.
const (
	envLibtpuPath = "WANDB_LIBTPU_PATH"
)

type libtpuCollector interface {
	Probe(ctx context.Context) (*libtpuProbeInfo, error)
	Sample(ctx context.Context) (map[string]any, error)
	Close() error
}

type libtpuProbeInfo struct {
	LibraryPath      string
	Version          string
	SupportedMetrics []string
	ResolvedMetrics  map[string]string
	Symbols          string // "GetLibtpuSdkApi" or legacy symbol names
}

// ---------- LibtpuSdkApi vtable layout ----------
//
// Recovered from libtpu.so (GetLibtpuSdkApi@@VERS_1.0) via disassembly.
// The struct has an 8-byte header (two uint32), then function pointers.
//
// All API functions follow the convention:
//   func(args *SomeArgs) -> *error_handle  (NULL on success)
//
// The args struct carries both inputs and outputs, modified in place.

const (
	// Vtable byte offsets from start of the LibtpuSdkApi struct.
	// The struct has an 8-byte header (two uint32), then function pointers.
	// Offsets verified against the CGO probe that successfully reads metrics.
	vtableErrorMessage         = 0x08
	vtableDestroyError         = 0x10
	vtableCreateClient         = 0x20
	vtableDestroyClient        = 0x28
	vtableGetMetric            = 0x50
	vtableGetMetricDescription = 0x58
	vtableGetMetricValues      = 0x60
)

// sdkCollector uses GetLibtpuSdkApi to call libtpu.so directly via purego.
type sdkCollector struct {
	logger *observability.CoreLogger

	path   string
	handle uintptr

	apiPtr uintptr // pointer to the LibtpuSdkApi struct
	client uintptr // client handle from CreateClient

	probeMu  sync.Mutex
	probe    *libtpuProbeInfo
	probeErr error
}

type desiredLibtpuMetric struct {
	LogicalName string
	Aliases     []string
}

var desiredLibtpuMetrics = []desiredLibtpuMetric{
	{
		LogicalName: "tensorcore_utilization",
		Aliases:     []string{"tensorcore_utilization", "tensorcore_util"},
	},
	{
		LogicalName: "duty_cycle_pct",
		Aliases:     []string{"duty_cycle_pct"},
	},
	{
		LogicalName: "hbm_capacity_total",
		Aliases:     []string{"hbm_capacity_total"},
	},
	{
		LogicalName: "hbm_capacity_usage",
		Aliases:     []string{"hbm_capacity_usage"},
	},
	{
		LogicalName: "buffer_transfer_latency",
		Aliases:     []string{"buffer_transfer_latency"},
	},
	{
		LogicalName: "host_to_device_transfer_latency",
		Aliases:     []string{"host_to_device_transfer_latency"},
	},
	{
		LogicalName: "device_to_host_transfer_latency",
		Aliases:     []string{"device_to_host_transfer_latency"},
	},
	{
		LogicalName: "collective_e2e_latency",
		Aliases:     []string{"collective_e2e_latency"},
	},
	{
		LogicalName: "grpc_tcp_min_rtt",
		Aliases:     []string{"grpc_tcp_min_rtt", "grpc_tcp_min_round_trip_times"},
	},
	{
		LogicalName: "grpc_tcp_delivery_rate",
		Aliases:     []string{"grpc_tcp_delivery_rate", "grpc_tcp_delivery_rates"},
	},
	{
		LogicalName: "hlo_exec_timing",
		Aliases:     []string{"hlo_exec_timing"},
	},
	{
		LogicalName: "hlo_queue_size",
		Aliases:     []string{"hlo_queue_size"},
	},
}

// newLibtpuCollector loads libtpu.so and calls GetLibtpuSdkApi to obtain
// the SDK function table. All subsequent metric calls go through this vtable
// using purego.SyscallN — no CGO required.
func newLibtpuCollector(logger *observability.CoreLogger) (*sdkCollector, error) {
	path := findLibtpuPath()
	if path == "" {
		return nil, fmt.Errorf("libtpu.so not found")
	}

	handle, err := purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_LOCAL)
	if err != nil {
		return nil, fmt.Errorf("dlopen %q: %w", path, err)
	}

	// Resolve GetLibtpuSdkApi.
	var getAPI func() uintptr
	purego.RegisterLibFunc(&getAPI, handle, "GetLibtpuSdkApi")
	apiPtr := getAPI()
	if apiPtr == 0 {
		purego.Dlclose(handle)
		return nil, fmt.Errorf("GetLibtpuSdkApi() returned NULL")
	}

	c := &sdkCollector{
		logger: logger,
		path:   path,
		handle: handle,
		apiPtr: apiPtr,
	}

	// Create a client immediately; this validates the vtable is functional.
	client, err := c.createClient()
	if err != nil {
		purego.Dlclose(handle)
		return nil, fmt.Errorf("CreateClient: %w", err)
	}
	c.client = client

	return c, nil
}

func (c *sdkCollector) Probe(ctx context.Context) (*libtpuProbeInfo, error) {
	_ = ctx

	c.probeMu.Lock()
	if c.probe != nil || c.probeErr != nil {
		probe, err := c.probe, c.probeErr
		c.probeMu.Unlock()
		return probe, err
	}
	c.probeMu.Unlock()

	// Try reading all known metric names to discover what's available.
	var supported []string
	for _, desired := range desiredLibtpuMetrics {
		for _, alias := range desired.Aliases {
			if _, _, err := c.readMetric(alias); err == nil {
				supported = append(supported, alias)
				break
			}
		}
	}
	sort.Strings(supported)

	resolved := resolveLibtpuMetricNames(supported)

	probe := &libtpuProbeInfo{
		LibraryPath:      c.path,
		SupportedMetrics: supported,
		ResolvedMetrics:  resolved,
		Symbols:          "GetLibtpuSdkApi",
	}

	c.probeMu.Lock()
	c.probe = probe
	c.probeMu.Unlock()
	return probe, nil
}

func (c *sdkCollector) Sample(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	probe, err := c.Probe(ctx)
	if err != nil {
		return nil, err
	}

	metrics := make(map[string]any)
	var sampleErrs []error

	for _, desired := range desiredLibtpuMetrics {
		if err := ctx.Err(); err != nil {
			return metrics, errors.Join(append(sampleErrs, err)...)
		}

		actualName, ok := probe.ResolvedMetrics[desired.LogicalName]
		if !ok || actualName == "" {
			continue
		}

		description, data, err := c.readMetric(actualName)
		if err != nil {
			sampleErrs = append(sampleErrs, fmt.Errorf("%s: %w", desired.LogicalName, err))
			continue
		}

		switch desired.LogicalName {
		case "tensorcore_utilization":
			appendIndexedFloatMetrics(metrics, "tpu.%d.tensorcoreUtilization", data)
		case "duty_cycle_pct":
			appendIndexedFloatMetrics(metrics, "tpu.%d.dutyCycle", data)
		case "hbm_capacity_total":
			appendIndexedFloatMetrics(metrics, "tpu.%d.hbmCapacityTotal", data)
		case "hbm_capacity_usage":
			appendIndexedFloatMetrics(metrics, "tpu.%d.hbmCapacityUsage", data)
		case "buffer_transfer_latency":
			appendLabeledDistributionMetrics(metrics, "tpu.bufferTransferLatency", "Us", description, data)
		case "host_to_device_transfer_latency":
			appendLabeledDistributionMetrics(metrics, "tpu.hostToDeviceTransferLatency", "Us", description, data)
		case "device_to_host_transfer_latency":
			appendLabeledDistributionMetrics(metrics, "tpu.deviceToHostTransferLatency", "Us", description, data)
		case "collective_e2e_latency":
			appendLabeledDistributionMetrics(metrics, "tpu.collectiveE2ELatency", "Us", description, data)
		case "grpc_tcp_min_rtt":
			appendDistributionMetrics(metrics, "tpu.grpcTcpMinRtt", "Us", description, data)
		case "grpc_tcp_delivery_rate":
			appendDistributionMetrics(metrics, "tpu.grpcTcpDeliveryRate", "Mbps", description, data)
		case "hlo_exec_timing":
			appendLabeledDistributionMetrics(metrics, "tpu.hloExecTiming", "Us", description, data)
		case "hlo_queue_size":
			appendColonValueMetrics(metrics, "tpu.hloQueueSize", data)
		}
	}

	if len(metrics) == 0 {
		return nil, errors.Join(sampleErrs...)
	}
	return metrics, errors.Join(sampleErrs...)
}

func (c *sdkCollector) Close() error {
	if c == nil {
		return nil
	}
	if c.client != 0 {
		c.destroyClient()
		c.client = 0
	}
	if c.handle != 0 {
		err := purego.Dlclose(c.handle)
		c.handle = 0
		return err
	}
	return nil
}

// ---------- SDK vtable calls via purego.SyscallN ----------

// vtableSlot reads the function pointer at the given byte offset in the API struct.
func (c *sdkCollector) vtableSlot(offset uintptr) uintptr {
	return *(*uintptr)(unsafe.Pointer(c.apiPtr + offset))
}

// createClient calls CreateClient through the vtable.
// Args layout: { void* client } — output only.
func (c *sdkCollector) createClient() (uintptr, error) {
	type createClientArgs struct {
		client uintptr
	}
	var args createClientArgs
	errHandle, _, _ := purego.SyscallN(c.vtableSlot(vtableCreateClient), uintptr(unsafe.Pointer(&args)))
	runtime.KeepAlive(&args)
	if err := c.consumeError(errHandle, "CreateClient"); err != nil {
		return 0, err
	}
	if args.client == 0 {
		return 0, fmt.Errorf("CreateClient returned nil client")
	}
	return args.client, nil
}

// destroyClient calls DestroyClient through the vtable.
func (c *sdkCollector) destroyClient() {
	if c.client == 0 {
		return
	}
	type destroyClientArgs struct {
		client uintptr
	}
	args := destroyClientArgs{client: c.client}
	purego.SyscallN(c.vtableSlot(vtableDestroyClient), uintptr(unsafe.Pointer(&args)))
	runtime.KeepAlive(&args)
}

// readMetric calls GetMetric, GetMetricDescription, and GetMetricValues.
func (c *sdkCollector) readMetric(metricName string) (string, []string, error) {
	metric, err := c.getMetric(metricName)
	if err != nil {
		return "", nil, err
	}

	desc, err := c.getMetricDescription(metric)
	if err != nil {
		return "", nil, err
	}

	values, err := c.getMetricValues(metric)
	if err != nil {
		return desc, nil, err
	}

	return desc, values, nil
}

// getMetric calls GetMetric(client, name) through the vtable.
// Args layout: { void* client; const char* metric_name; void* metric }
func (c *sdkCollector) getMetric(name string) (uintptr, error) {
	cname := cString(name)
	type getMetricArgs struct {
		client     uintptr
		metricName uintptr // *byte
		metric     uintptr
	}
	args := getMetricArgs{
		client:     c.client,
		metricName: uintptr(unsafe.Pointer(&cname[0])),
	}
	errHandle, _, _ := purego.SyscallN(c.vtableSlot(vtableGetMetric), uintptr(unsafe.Pointer(&args)))
	runtime.KeepAlive(cname)
	runtime.KeepAlive(&args)
	if err := c.consumeError(errHandle, fmt.Sprintf("GetMetric(%q)", name)); err != nil {
		return 0, err
	}
	if args.metric == 0 {
		return 0, fmt.Errorf("GetMetric(%q): nil handle", name)
	}
	return args.metric, nil
}

// getMetricDescription calls GetMetricDescription(metric) through the vtable.
// Args layout: { const void* metric; const char* description; size_t description_len }
func (c *sdkCollector) getMetricDescription(metric uintptr) (string, error) {
	type getMetricDescriptionArgs struct {
		metric         uintptr
		description    uintptr // *byte
		descriptionLen uintptr // size_t
	}
	args := getMetricDescriptionArgs{metric: metric}
	errHandle, _, _ := purego.SyscallN(c.vtableSlot(vtableGetMetricDescription), uintptr(unsafe.Pointer(&args)))
	runtime.KeepAlive(&args)
	if err := c.consumeError(errHandle, "GetMetricDescription"); err != nil {
		return "", err
	}
	if args.description == 0 || args.descriptionLen == 0 {
		return "", nil
	}
	return goStringN(args.description, args.descriptionLen), nil
}

// getMetricValues calls GetMetricValues(metric) through the vtable.
// Args layout: { const void* metric; const char** values; size_t value_count }
func (c *sdkCollector) getMetricValues(metric uintptr) ([]string, error) {
	type getMetricValuesArgs struct {
		metric     uintptr
		values     uintptr // **byte (array of C strings)
		valueCount uintptr // size_t
	}
	args := getMetricValuesArgs{metric: metric}
	errHandle, _, _ := purego.SyscallN(c.vtableSlot(vtableGetMetricValues), uintptr(unsafe.Pointer(&args)))
	runtime.KeepAlive(&args)
	if err := c.consumeError(errHandle, "GetMetricValues"); err != nil {
		return nil, err
	}
	count := int(args.valueCount)
	if count == 0 || args.values == 0 {
		return nil, nil
	}

	// Read the char** array: each element is a pointer to a C string.
	result := make([]string, 0, count)
	for i := range count {
		strPtr := *(*uintptr)(unsafe.Pointer(args.values + uintptr(i)*unsafe.Sizeof(uintptr(0))))
		if strPtr == 0 {
			result = append(result, "")
			continue
		}
		result = append(result, cStringFromPtr(strPtr))
	}
	return result, nil
}

// consumeError reads and destroys a libtpu error handle.
func (c *sdkCollector) consumeError(errHandle uintptr, context string) error {
	if errHandle == 0 {
		return nil
	}

	// ErrorMessage: { void* error; const char* message; size_t message_len }
	type errorMessageArgs struct {
		errHandle  uintptr
		message    uintptr
		messageLen uintptr
	}
	msgArgs := errorMessageArgs{errHandle: errHandle}
	purego.SyscallN(c.vtableSlot(vtableErrorMessage), uintptr(unsafe.Pointer(&msgArgs)))
	runtime.KeepAlive(&msgArgs)

	msg := "unknown error"
	if msgArgs.message != 0 && msgArgs.messageLen > 0 {
		msg = goStringN(msgArgs.message, msgArgs.messageLen)
	}

	// DestroyError: { void* error }
	type destroyErrorArgs struct {
		errHandle uintptr
	}
	destroyArgs := destroyErrorArgs{errHandle: errHandle}
	purego.SyscallN(c.vtableSlot(vtableDestroyError), uintptr(unsafe.Pointer(&destroyArgs)))
	runtime.KeepAlive(&destroyArgs)

	return fmt.Errorf("%s: %s", context, msg)
}

// ---------- String helpers ----------

func goStringN(ptr uintptr, n uintptr) string {
	if ptr == 0 || n == 0 {
		return ""
	}
	return unsafe.String((*byte)(unsafe.Pointer(ptr)), int(n))
}

func cString(value string) []byte {
	b := make([]byte, len(value)+1)
	copy(b, value)
	return b
}

func cStringFromPtr(p uintptr) string {
	if p == 0 {
		return ""
	}
	var data []byte
	for offset := uintptr(0); ; offset++ {
		current := *(*byte)(unsafe.Pointer(p + offset))
		if current == 0 {
			break
		}
		data = append(data, current)
	}
	return string(data)
}

// ---------- Metric name resolution ----------

func resolveLibtpuMetricNames(supported []string) map[string]string {
	resolved := make(map[string]string)
	if len(supported) == 0 {
		return resolved
	}

	supportedSet := make(map[string]struct{}, len(supported))
	for _, metric := range supported {
		supportedSet[metric] = struct{}{}
	}

	for _, desired := range desiredLibtpuMetrics {
		for _, alias := range desired.Aliases {
			if _, ok := supportedSet[alias]; ok {
				resolved[desired.LogicalName] = alias
				break
			}
		}
	}
	return resolved
}

// ---------- Metric data parsing ----------
// The libtpu SDK returns metric values as C strings.
// These helpers parse them into structured output.

func appendIndexedFloatMetrics(out map[string]any, keyFmt string, data []string) {
	for idx, raw := range data {
		value, ok := parseFloatString(raw)
		if !ok {
			continue
		}
		out[fmt.Sprintf(keyFmt, idx)] = value
	}
}

func appendLabeledDistributionMetrics(out map[string]any, baseKey, unitSuffix, description string, data []string) {
	for _, raw := range data {
		parts := splitMetricLine(raw)
		if len(parts) < 2 {
			continue
		}
		label := sanitizeMetricLabel(parts[0])
		stats := parts[1:]
		names := distributionStatNames(description, len(stats))
		for idx, rawValue := range stats {
			value, ok := parseFloatString(rawValue)
			if !ok || idx >= len(names) {
				continue
			}
			out[fmt.Sprintf("%s.%s.%s%s", baseKey, label, names[idx], unitSuffix)] = value
		}
	}
}

func appendDistributionMetrics(out map[string]any, baseKey, unitSuffix, description string, data []string) {
	stats := data
	if len(data) == 1 {
		parts := splitMetricLine(data[0])
		if len(parts) > 1 {
			stats = parts
		}
	}
	names := distributionStatNames(description, len(stats))
	for idx, rawValue := range stats {
		value, ok := parseFloatString(rawValue)
		if !ok || idx >= len(names) {
			continue
		}
		out[fmt.Sprintf("%s.%s%s", baseKey, names[idx], unitSuffix)] = value
	}
}

func appendColonValueMetrics(out map[string]any, baseKey string, data []string) {
	for idx, raw := range data {
		left, right, found := strings.Cut(raw, ":")
		if !found {
			left = fmt.Sprintf("item_%d", idx)
			right = raw
		}
		value, ok := parseFloatString(right)
		if !ok {
			continue
		}
		out[fmt.Sprintf("%s.%s", baseKey, sanitizeMetricLabel(left))] = value
	}
}

func distributionStatNames(description string, count int) []string {
	description = strings.ToLower(description)
	switch count {
	case 5:
		switch {
		case strings.Contains(description, "p99") && !strings.Contains(description, "p95"):
			return []string{"mean", "p50", "p90", "p99", "p999"}
		default:
			return []string{"mean", "p50", "p90", "p95", "p999"}
		}
	case 4:
		return []string{"p50", "p90", "p95", "p999"}
	default:
		names := make([]string, count)
		for i := range count {
			names[i] = fmt.Sprintf("stat%d", i)
		}
		return names
	}
}

func splitMetricLine(raw string) []string {
	raw = strings.TrimSpace(raw)
	raw = strings.Trim(raw, "[]")
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		part = strings.Trim(part, "\"'")
		if part != "" {
			result = append(result, part)
		}
	}
	return result
}

func parseFloatString(raw string) (float64, bool) {
	raw = strings.TrimSpace(strings.Trim(raw, "\"'"))
	if raw == "" {
		return 0, false
	}
	if value, err := strconv.ParseFloat(raw, 64); err == nil {
		return value, true
	}
	fields := strings.Fields(raw)
	if len(fields) > 0 {
		if value, err := strconv.ParseFloat(fields[0], 64); err == nil {
			return value, true
		}
	}
	return 0, false
}

func sanitizeMetricLabel(label string) string {
	label = strings.ToLower(strings.TrimSpace(label))
	label = strings.ReplaceAll(label, "+", "_plus_")
	label = strings.ReplaceAll(label, "%", "pct")
	var b strings.Builder
	lastUnderscore := false
	for _, r := range label {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
			lastUnderscore = false
		case r >= '0' && r <= '9':
			b.WriteRune(r)
			lastUnderscore = false
		default:
			if !lastUnderscore {
				b.WriteByte('_')
				lastUnderscore = true
			}
		}
	}
	cleaned := strings.Trim(b.String(), "_")
	if cleaned == "" {
		return "unknown"
	}
	return cleaned
}

// ---------- libtpu.so discovery ----------

func findLibtpuPath() string {
	if libraryPath := resolveLibtpuFilePath(strings.TrimSpace(os.Getenv(envLibtpuPath))); libraryPath != "" {
		return libraryPath
	}
	for _, env := range []string{"TPU_LIBRARY_PATH", "LIBTPU_PATH"} {
		if libraryPath := resolveLibtpuFilePath(strings.TrimSpace(os.Getenv(env))); libraryPath != "" {
			return libraryPath
		}
	}

	candidates := []string{
		"/lib/libtpu.so",
		"/usr/lib/libtpu.so",
		"/usr/local/lib/libtpu.so",
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		for _, pattern := range []string{
			filepath.Join(home, ".local/lib/python*/site-packages/libtpu/libtpu.so"),
			filepath.Join(home, ".local/lib/python*/site-packages/torch_xla/lib/libtpu.so"),
			filepath.Join(home, ".venv/lib/python*/site-packages/libtpu/libtpu.so"),
		} {
			matches, _ := filepath.Glob(pattern)
			candidates = append(candidates, matches...)
		}
	}
	for _, pattern := range []string{
		"/usr/local/lib/python*/dist-packages/libtpu/libtpu.so",
		"/usr/local/lib/python*/dist-packages/torch_xla/lib/libtpu.so",
		"/usr/lib/python*/dist-packages/libtpu/libtpu.so",
		"/usr/lib/python*/dist-packages/torch_xla/lib/libtpu.so",
	} {
		matches, _ := filepath.Glob(pattern)
		candidates = append(candidates, matches...)
	}

	seen := make(map[string]struct{}, len(candidates))
	for _, candidate := range candidates {
		candidate = strings.TrimSpace(candidate)
		if candidate == "" {
			continue
		}
		if _, ok := seen[candidate]; ok {
			continue
		}
		seen[candidate] = struct{}{}
		if resolved := resolveLibtpuFilePath(candidate); resolved != "" {
			return resolved
		}
	}
	return ""
}

func resolveLibtpuFilePath(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}
	info, err := os.Stat(path)
	if err != nil {
		return ""
	}
	if info.IsDir() {
		joined := filepath.Join(path, "libtpu.so")
		if fi, err := os.Stat(joined); err == nil && !fi.IsDir() {
			return joined
		}
		return ""
	}
	return path
}

func dedupeSortedStrings(values []string) []string {
	cleaned := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		value = strings.TrimSpace(strings.Trim(value, "\"'"))
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		cleaned = append(cleaned, value)
	}
	sort.Strings(cleaned)
	return cleaned
}
