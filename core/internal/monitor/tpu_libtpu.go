//go:build linux

package monitor

import (
	"context"
	"debug/elf"
	"encoding/json"
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
	envLibtpuPath        = "WANDB_LIBTPU_PATH"
	envListSymbol        = "WANDB_LIBTPU_MON_LIST_SYMBOL"
	envGetSymbol         = "WANDB_LIBTPU_MON_GET_SYMBOL"
	envDescriptionSymbol = "WANDB_LIBTPU_MON_DESC_SYMBOL"
	envDataSymbol        = "WANDB_LIBTPU_MON_DATA_SYMBOL"
	envFreeSymbol        = "WANDB_LIBTPU_MON_FREE_SYMBOL"
	envVersionSymbol     = "WANDB_LIBTPU_MON_VERSION_SYMBOL"
	envPjrtSymbol        = "WANDB_LIBTPU_PJRT_SYMBOL"
)

type libtpuCollector interface {
	Probe(ctx context.Context) (*libtpuProbeInfo, error)
	Sample(ctx context.Context) (map[string]any, error)
	Close() error
}

type libtpuSymbols struct {
	GetPjrtAPI           string
	ListSupportedMetrics string
	GetMetric            string
	MetricDescription    string
	MetricData           string
	MetricFree           string
	Version              string
}

type libtpuProbeInfo struct {
	LibraryPath      string
	Version          string
	SupportedMetrics []string
	ResolvedMetrics  map[string]string
	Symbols          libtpuSymbols
}

type puregoLibtpuCollector struct {
	logger *observability.CoreLogger

	path   string
	handle uintptr

	listSupportedMetrics func() uintptr
	getMetric            func(*byte) uintptr
	metricDescription    func(uintptr) uintptr
	metricData           func(uintptr) uintptr
	metricFree           func(uintptr)
	getVersion           func() uintptr
	getPjrtAPI           func() uintptr

	exportedSymbols []string
	symbols         libtpuSymbols

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
		Aliases: []string{
			"tensorcore_utilization",
			"tensorcore_util",
		},
	},
	{
		LogicalName: "buffer_transfer_latency",
		Aliases: []string{
			"buffer_transfer_latency",
		},
	},
	{
		LogicalName: "host_to_device_transfer_latency",
		Aliases: []string{
			"host_to_device_transfer_latency",
		},
	},
	{
		LogicalName: "device_to_host_transfer_latency",
		Aliases: []string{
			"device_to_host_transfer_latency",
		},
	},
	{
		LogicalName: "collective_e2e_latency",
		Aliases: []string{
			"collective_e2e_latency",
		},
	},
	{
		LogicalName: "grpc_tcp_min_rtt",
		Aliases: []string{
			"grpc_tcp_min_rtt",
			"grpc_tcp_min_round_trip_times",
		},
	},
	{
		LogicalName: "grpc_tcp_delivery_rate",
		Aliases: []string{
			"grpc_tcp_delivery_rate",
			"grpc_tcp_delivery_rates",
		},
	},
	{
		LogicalName: "hlo_exec_timing",
		Aliases: []string{
			"hlo_exec_timing",
		},
	},
	{
		LogicalName: "hlo_queue_size",
		Aliases: []string{
			"hlo_queue_size",
		},
	},
}

var listSupportedMetricSymbolCandidates = []string{
	"TpuMonitoringListSupportedMetrics",
	"LibtpuMonitoringListSupportedMetrics",
	"libtpu_monitoring_list_supported_metrics",
	"libtpu_list_supported_metrics",
	"list_supported_metrics",
}

var getMetricSymbolCandidates = []string{
	"TpuMonitoringGetMetric",
	"LibtpuMonitoringGetMetric",
	"libtpu_monitoring_get_metric",
	"libtpu_get_metric",
	"get_metric",
}

var metricDescriptionSymbolCandidates = []string{
	"TpuMetricDescription",
	"LibtpuMetricDescription",
	"libtpu_metric_description",
	"metric_description",
	"description",
}

var metricDataSymbolCandidates = []string{
	"TpuMetricData",
	"LibtpuMetricData",
	"libtpu_metric_data",
	"metric_data",
	"data",
}

var metricFreeSymbolCandidates = []string{
	"TpuMetricFree",
	"LibtpuMetricFree",
	"libtpu_metric_free",
	"metric_free",
	"free_metric",
}

var versionSymbolCandidates = []string{
	"LibtpuVersion",
	"LibtpuGetVersion",
	"libtpu_version",
	"libtpu_get_version",
	"GetLibtpuVersion",
	"GetVersion",
}

var pjrtSymbolCandidates = []string{
	"GetPjrtApi",
}

// newLibtpuCollector loads libtpu.so directly with purego.
//
// The monitoring ABI is not publicly documented in the sources available here, so
// symbol resolution is layered:
//  1. explicit env overrides
//  2. common candidate names
//  3. ELF-exported symbol heuristics
//
// If your environment uses different symbol names, set the WANDB_LIBTPU_MON_* env vars.
func newLibtpuCollector(logger *observability.CoreLogger) (*puregoLibtpuCollector, error) {
	path := findLibtpuPath()
	if path == "" {
		return nil, fmt.Errorf("libtpu.so not found")
	}

	handle, err := purego.Dlopen(path, purego.RTLD_NOW|purego.RTLD_LOCAL)
	if err != nil {
		return nil, fmt.Errorf("dlopen %q: %w", path, err)
	}

	c := &puregoLibtpuCollector{
		logger:  logger,
		path:    path,
		handle:  handle,
		symbols: libtpuSymbols{},
	}
	c.exportedSymbols, _ = exportedELFSymbols(path)

	_ = c.resolveOptionalSymbol(&c.getPjrtAPI, &c.symbols.GetPjrtAPI, os.Getenv(envPjrtSymbol), pjrtSymbolCandidates)

	_ = c.resolveOptionalSymbol(&c.listSupportedMetrics, &c.symbols.ListSupportedMetrics, os.Getenv(envListSymbol), listSupportedMetricSymbolCandidates)
	_ = c.resolveOptionalSymbol(&c.metricFree, &c.symbols.MetricFree, os.Getenv(envFreeSymbol), metricFreeSymbolCandidates)
	_ = c.resolveOptionalSymbol(&c.getVersion, &c.symbols.Version, os.Getenv(envVersionSymbol), versionSymbolCandidates)

	if err := c.resolveRequiredSymbol(&c.getMetric, &c.symbols.GetMetric, os.Getenv(envGetSymbol), getMetricSymbolCandidates, []string{"get", "metric"}); err != nil {
		_ = c.Close()
		return nil, err
	}
	if err := c.resolveRequiredSymbol(&c.metricDescription, &c.symbols.MetricDescription, os.Getenv(envDescriptionSymbol), metricDescriptionSymbolCandidates, []string{"description"}); err != nil {
		_ = c.Close()
		return nil, err
	}
	if err := c.resolveRequiredSymbol(&c.metricData, &c.symbols.MetricData, os.Getenv(envDataSymbol), metricDataSymbolCandidates, []string{"data"}); err != nil {
		_ = c.Close()
		return nil, err
	}

	return c, nil
}

func (c *puregoLibtpuCollector) Probe(ctx context.Context) (*libtpuProbeInfo, error) {
	_ = ctx

	c.probeMu.Lock()
	if c.probe != nil || c.probeErr != nil {
		probe, err := c.probe, c.probeErr
		c.probeMu.Unlock()
		return probe, err
	}
	c.probeMu.Unlock()

	supportedMetrics, _ := c.listSupportedMetricNames()
	resolvedMetrics := resolveLibtpuMetricNames(supportedMetrics)
	if len(resolvedMetrics) == 0 {
		// Fall back to first alias for optimistic probing when the list symbol is
		// not exported. Sample() still treats per-metric failures independently.
		resolvedMetrics = fallbackResolvedLibtpuMetrics()
	}

	version := ""
	if c.getVersion != nil {
		version = cStringFromPtr(c.getVersion())
	}

	probe := &libtpuProbeInfo{
		LibraryPath:      c.path,
		Version:          strings.TrimSpace(version),
		SupportedMetrics: supportedMetrics,
		ResolvedMetrics:  resolvedMetrics,
		Symbols:          c.symbols,
	}

	c.probeMu.Lock()
	c.probe = probe
	c.probeMu.Unlock()
	return probe, nil
}

func (c *puregoLibtpuCollector) Sample(ctx context.Context) (map[string]any, error) {
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

func (c *puregoLibtpuCollector) Close() error {
	if c == nil || c.handle == 0 {
		return nil
	}
	err := purego.Dlclose(c.handle)
	c.handle = 0
	return err
}

func (c *puregoLibtpuCollector) readMetric(metricName string) (string, []string, error) {
	name := cString(metricName)
	handle := c.getMetric(&name[0])
	runtime.KeepAlive(name)
	if handle == 0 {
		return "", nil, fmt.Errorf("get_metric returned nil")
	}
	if c.metricFree != nil {
		defer c.metricFree(handle)
	}

	description := cStringFromPtr(c.metricDescription(handle))
	rawData := cStringFromPtr(c.metricData(handle))
	return description, parseMetricDataString(rawData), nil
}

func (c *puregoLibtpuCollector) listSupportedMetricNames() ([]string, error) {
	if c.listSupportedMetrics == nil {
		return nil, nil
	}
	raw := cStringFromPtr(c.listSupportedMetrics())
	if strings.TrimSpace(raw) == "" {
		return nil, nil
	}
	return parseMetricListString(raw), nil
}

func (c *puregoLibtpuCollector) resolveOptionalSymbol(fn any, dst *string, envName string, candidates []string) error {
	if name, ok := c.resolveSymbolName(envName, candidates, nil); ok {
		if err := registerLibFunc(c.handle, name, fn); err != nil {
			return err
		}
		*dst = name
	}
	return nil
}

func (c *puregoLibtpuCollector) resolveRequiredSymbol(fn any, dst *string, envName string, candidates []string, heuristicTokens []string) error {
	name, ok := c.resolveSymbolName(envName, candidates, heuristicTokens)
	if !ok {
		return fmt.Errorf(
			"failed to resolve required libtpu symbol; set %s/%s/%s and inspect %s with `nm -D %s | grep -i -E 'metric|monitor|tpu'`",
			envGetSymbol,
			envDescriptionSymbol,
			envDataSymbol,
			filepath.Base(c.path),
			c.path,
		)
	}
	if err := registerLibFunc(c.handle, name, fn); err != nil {
		return fmt.Errorf("register %q: %w", name, err)
	}
	*dst = name
	return nil
}

func (c *puregoLibtpuCollector) resolveSymbolName(envName string, candidates []string, heuristicTokens []string) (string, bool) {
	if envName != "" {
		if symbolExists(c.handle, envName) {
			return envName, true
		}
	}

	for _, name := range candidates {
		if name != "" && symbolExists(c.handle, name) {
			return name, true
		}
	}

	guessed := guessUniqueSymbol(c.exportedSymbols, heuristicTokens)
	if guessed != "" && symbolExists(c.handle, guessed) {
		return guessed, true
	}
	return "", false
}

func registerLibFunc(handle uintptr, name string, fn any) error {
	if _, err := purego.Dlsym(handle, name); err != nil {
		return err
	}
	purego.RegisterLibFunc(fn, handle, name)
	return nil
}

func symbolExists(handle uintptr, name string) bool {
	if name == "" {
		return false
	}
	_, err := purego.Dlsym(handle, name)
	return err == nil
}

func guessUniqueSymbol(symbols []string, tokens []string) string {
	if len(symbols) == 0 || len(tokens) == 0 {
		return ""
	}
	matches := make([]string, 0, 4)
	for _, symbol := range symbols {
		normalized := normalizeMetricName(symbol)
		ok := true
		for _, token := range tokens {
			if !strings.Contains(normalized, token) {
				ok = false
				break
			}
		}
		if ok {
			matches = append(matches, symbol)
		}
	}
	if len(matches) == 1 {
		return matches[0]
	}
	return ""
}

func exportedELFSymbols(path string) ([]string, error) {
	f, err := elf.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	dynamicSymbols, err := f.DynamicSymbols()
	if err != nil {
		return nil, err
	}

	names := make([]string, 0, len(dynamicSymbols))
	for _, symbol := range dynamicSymbols {
		if elf.ST_BIND(symbol.Info) == elf.STB_GLOBAL && symbol.Name != "" {
			names = append(names, symbol.Name)
		}
	}
	sort.Strings(names)
	return names, nil
}

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

func fallbackResolvedLibtpuMetrics() map[string]string {
	resolved := make(map[string]string, len(desiredLibtpuMetrics))
	for _, desired := range desiredLibtpuMetrics {
		if len(desired.Aliases) > 0 {
			resolved[desired.LogicalName] = desired.Aliases[0]
		}
	}
	return resolved
}

func parseMetricListString(raw string) []string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}

	var jsonValues []string
	if err := json.Unmarshal([]byte(raw), &jsonValues); err == nil {
		return dedupeSortedStrings(jsonValues)
	}

	parts := splitMetricLine(raw)
	if len(parts) == 0 {
		fields := strings.FieldsFunc(raw, func(r rune) bool {
			switch r {
			case '\n', '\r', '\t', ',', ';', '[', ']':
				return true
			default:
				return false
			}
		})
		parts = fields
	}
	return dedupeSortedStrings(parts)
}

func parseMetricDataString(raw string) []string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}

	var jsonValues []string
	if err := json.Unmarshal([]byte(raw), &jsonValues); err == nil {
		return jsonValues
	}

	lines := strings.Split(raw, "\n")
	if len(lines) == 1 {
		return splitMetricLine(raw)
	}

	result := make([]string, 0, len(lines))
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line != "" {
			result = append(result, line)
		}
	}
	return result
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
		patterns := []string{
			filepath.Join(home, ".local/lib/python*/site-packages/libtpu/libtpu.so"),
			filepath.Join(home, ".local/lib/python*/site-packages/torch_xla/lib/libtpu.so"),
		}
		for _, pattern := range patterns {
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
	if info, err := os.Stat(path); err == nil {
		if info.IsDir() {
			joined := filepath.Join(path, "libtpu.so")
			if fileInfo, fileErr := os.Stat(joined); fileErr == nil && !fileInfo.IsDir() {
				return joined
			}
			return ""
		}
		return path
	}
	return ""
}
