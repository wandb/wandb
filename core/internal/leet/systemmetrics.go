package leet

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

const DefaultSystemMetricSeriesName = "Default"

// MetricDef represents a system metric definition needed for displaying it on a chart.
type MetricDef struct {
	Name       string
	Unit       string         // Unit: "%", "°C", "W", "MB", etc.
	MinY       float64        // Default min Y value
	MaxY       float64        // Default max Y value
	Percentage bool           // Whether this is a percentage metric
	AutoRange  bool           // Whether to auto-adjust Y range based on data
	Regex      *regexp.Regexp // Pattern to match metric names (including suffixes)
}

// Title returns the title to display on the metric chart.
func (md *MetricDef) Title() string {
	if md.Unit != "" {
		return fmt.Sprintf("%s (%s)", md.Name, md.Unit)
	}
	return md.Name
}

// metricDefs holds all metric definitions.
//
// Patterns are ordered from most specific to least specific for proper matching.
var metricDefs = []MetricDef{
	// CPU metrics
	{Name: "Process CPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu(\/l:.+)?$`)},
	{Name: "CPU Core", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.\d+\.cpu_percent(\/l:.+)?$`)},
	{Name: "Apple E-cores", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.ecpu_percent(\/l:.+)?$`)},
	{Name: "Apple E-cores Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.ecpu_freq(\/l:.+)?$`)},
	{Name: "Apple P-cores", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.pcpu_percent(\/l:.+)?$`)},
	{Name: "Apple P-cores Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.pcpu_freq(\/l:.+)?$`)},
	{Name: "CPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.avg_temp(\/l:.+)?$`)},
	{Name: "CPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.powerWatts(\/l:.+)?$`)},

	// Memory metrics
	{Name: "System Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^memory_percent(\/l:.+)?$`)},
	{Name: "RAM Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^memory\.used(\/l:.+)?$`)},
	{Name: "RAM Used", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^memory\.used_percent(\/l:.+)?$`)},

	// Swap metrics
	{Name: "Swap Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^swap\.used(\/l:.+)?$`)},
	{Name: "Swap Used", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^swap\.used_percent(\/l:.+)?$`)},

	// Process metrics
	{Name: "Process Memory", Unit: "MB", MinY: 0, MaxY: 32768, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.memory\.rssMB(\/l:.+)?$`)},
	{Name: "Process Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^proc\.memory\.percent(\/l:.+)?$`)},
	{Name: "Process Memory Available", Unit: "MB", MinY: 0, MaxY: 32768, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.memory\.availableMB(\/l:.+)?$`)},
	{Name: "Process CPU Threads", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.cpu\.threads(\/l:.+)?$`)},

	// Disk metrics - handle both aggregated and per-device
	{Name: "Disk", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^disk$`)},
	{Name: "Disk", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.usagePercent(\/l:.+)?$`)},
	{Name: "Disk", Unit: "GB", MinY: 0, MaxY: 1000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.usageGB(\/l:.+)?$`)},
	// Per-device I/O patterns (e.g., disk.disk4.in, disk.disk1.out) - CUMULATIVE
	{Name: "Disk I/O Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.(in|out)(\/l:.+)?$`)},
	// Aggregated I/O patterns - CUMULATIVE
	{Name: "Disk Read Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.in(\/l:.+)?$`)},
	{Name: "Disk Write Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.out(\/l:.+)?$`)},

	// Network metrics - treat as rates instead of cumulative
	{Name: "Network Rx", Unit: "B", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^network\.recv(\/l:.+)?$`)},
	{Name: "Network Tx", Unit: "B", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^network\.sent(\/l:.+)?$`)},

	// System power
	{Name: "System Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^system\.powerWatts(\/l:.+)?$`)},

	// Apple Neural Engine
	{Name: "Neural Engine Power", Unit: "W", MinY: 0, MaxY: 50, AutoRange: true,
		Regex: regexp.MustCompile(`^ane\.power(\/l:.+)?$`)},

	// GPU metrics
	{Name: "GPU Utilization", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.gpu(\/l:.+)?$`)},
	{Name: "GPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.temp(\/l:.+)?$`)},
	{Name: "GPU Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.freq(\/l:.+)?$`)},
	{Name: "GPU Memory Access", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memory(\/l:.+)?$`)},
	{Name: "GPU Memory Allocated", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryAllocated(\/l:.+)?$`)},
	{Name: "GPU Memory Allocated", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryAllocatedBytes(\/l:.+)?$`)},
	{Name: "GPU Memory Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryUsed(\/l:.+)?$`)},
	{Name: "GPU Recovery Count", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.recoveryCount(\/l:.+)?$`)},
	{Name: "GPU Power Limit", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.enforcedPowerLimitWatts(\/l:.+)?$`)},
	{Name: "GPU Power", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.powerPercent(\/l:.+)?$`)},
	{Name: "GPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.powerWatts(\/l:.+)?$`)},
	{Name: "GPU SM Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smClock(\/l:.+)?$`)},
	{Name: "GPU Graphics Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.graphicsClock(\/l:.+)?$`)},
	{Name: "GPU Memory Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryClock(\/l:.+)?$`)},
	{Name: "GPU Corrected Errors", Unit: "", MinY: 0, MaxY: 1000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.correctedMemoryErrors(\/l:.+)?$`)},
	{Name: "GPU Uncorrected Errors", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.uncorrectedMemoryErrors(\/l:.+)?$`)},
	{Name: "GPU Encoder", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.encoderUtilization(\/l:.+)?$`)},
	{Name: "GPU SM Active", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smActive(\/l:.+)?$`)},
	{Name: "GPU SM Occupancy", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smOccupancy(\/l:.+)?$`)},
	{Name: "GPU Tensor Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeTensorActive(\/l:.+)?$`)},
	{Name: "GPU DRAM Active", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.dramActive(\/l:.+)?$`)},
	{Name: "GPU FP64 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp64Active(\/l:.+)?$`)},
	{Name: "GPU FP32 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp32Active(\/l:.+)?$`)},
	{Name: "GPU FP16 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp16Active(\/l:.+)?$`)},
	{Name: "GPU Tensor HMMA", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeTensorHmmaActive(\/l:.+)?$`)},
	{Name: "GPU PCIe Tx", Unit: "GB/s", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pcieTxBytes(\/l:.+)?$`)},
	{Name: "GPU PCIe Rx", Unit: "GB/s", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pcieRxBytes(\/l:.+)?$`)},
	{Name: "GPU NVLink Tx", Unit: "GB/s", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.nvlinkTxBytes(\/l:.+)?$`)},
	{Name: "GPU NVLink Rx", Unit: "GB/s", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.nvlinkRxBytes(\/l:.+)?$`)},

	// Process GPU metrics
	{Name: "Process GPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.gpu(\/l:.+)?$`)},
	{Name: "Process GPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.temp(\/l:.+)?$`)},
	{Name: "Process GPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memory(\/l:.+)?$`)},
	{Name: "Process GPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocated(\/l:.+)?$`)},
	{Name: "Process GPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocatedBytes(\/l:.+)?$`)},
	{Name: "Process GPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryUsedBytes(\/l:.+)?$`)},
	{Name: "Process GPU Power Limit", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.enforcedPowerLimitWatts(\/l:.+)?$`)},
	{Name: "Process GPU Power", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.powerPercent(\/l:.+)?$`)},
	{Name: "Process GPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.powerWatts(\/l:.+)?$`)},

	// TPU metrics
	{Name: "TPU Duty Cycle", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.dutyCycle(\/l:.+)?$`)},
	{Name: "TPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.memory[Uu]sage(\/l:.+)?$`)},
	{Name: "TPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.memory[Uu]sage[Bb]ytes(\/l:.+)?$`)},

	// IPU metrics
	{Name: "IPU Board Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.average board temp(\/l:.+)?$`)},
	{Name: "IPU Die Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.average die temp(\/l:.+)?$`)},
	{Name: "IPU Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.clock(\/l:.+)?$`)},
	{Name: "IPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu power(\/l:.+)?$`)},
	{Name: "IPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(%\)(\/l:.+)?$`)},
	{Name: "IPU Session", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(session\)(\/l:.+)?$`)},

	// Trainium metrics
	{Name: "Neuron Core", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_utilization(\/l:.+)?$`)},
	{Name: "Trainium Host Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_total_memory_usage(\/l:.+)?$`)},
	{Name: "Neuron Device Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.neuron_device_total_memory_usage(\/l:.+)?$`)},
	{Name: "Trainium Host App Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.application_memory(\/l:.+)?$`)},
	{Name: "Trainium Host Constants", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.constants(\/l:.+)?$`)},
	{Name: "Trainium Host DMA", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.dma_buffers(\/l:.+)?$`)},
	{Name: "Trainium Host Tensors", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.tensors(\/l:.+)?$`)},
	{Name: "Neuron Constants", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.constants(\/l:.+)?$`)},
	{Name: "Neuron Model Code", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_code(\/l:.+)?$`)},
	{Name: "Neuron Scratchpad", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_shared_scratchpad(\/l:.+)?$`)},
	{Name: "Neuron Runtime", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.runtime_memory(\/l:.+)?$`)},
	{Name: "Neuron Tensors", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.tensors(\/l:.+)?$`)},
}

// MatchMetricDef finds the matching definition for a given metric name
func MatchMetricDef(metricName string) *MetricDef {
	// Remove any prefix slashes if present
	metricName = strings.TrimPrefix(metricName, "/")

	// Try each pattern in order (most specific first)
	for i := range metricDefs {
		if metricDefs[i].Regex.MatchString(metricName) {
			return &metricDefs[i]
		}
	}

	return nil
}

// ExtractBaseKey extracts the base metric name for grouping.
//
// For example, "gpu.0.temp" -> "gpu.temp", "cpu.0.cpu_percent" -> "cpu.cpu_percent"
// "disk.disk4.in" -> "disk.in_out" (special case for disk I/O)
// Also handles suffixes like "/l:..." for shared mode.
func ExtractBaseKey(metricName string) string {
	// Remove suffix if present
	if idx := strings.Index(metricName, "/l:"); idx > 0 {
		metricName = metricName[:idx]
	}

	parts := strings.Split(metricName, ".")

	// Special handling for disk I/O metrics: disk.diskN.in/out -> disk.in_out
	if len(parts) == 3 && parts[0] == "disk" && strings.HasPrefix(parts[1], "disk") &&
		(parts[2] == "in" || parts[2] == "out") {
		return "disk.io_per_device"
	}

	// Handle patterns like "gpu.0.temp" -> "gpu.temp"
	if len(parts) >= 3 && isNumeric(parts[1]) {
		return parts[0] + "." + strings.Join(parts[2:], ".")
	}

	// Handle patterns like "gpu.process.0.temp" -> "gpu.process.temp"
	if len(parts) >= 4 && parts[1] == "process" && isNumeric(parts[2]) {
		return parts[0] + "." + parts[1] + "." + strings.Join(parts[3:], ".")
	}

	return metricName
}

// ExtractSeriesName extracts the series identifier from a metric name
// e.g., "gpu.0.temp" -> "GPU 0", "disk.disk4.in" -> "disk4 in"
func ExtractSeriesName(metricName string) string {
	// Remove suffix if present
	if idx := strings.Index(metricName, "/l:"); idx > 0 {
		metricName = metricName[:idx]
	}

	parts := strings.Split(metricName, ".")

	// Handle disk I/O patterns like "disk.disk4.in"
	if len(parts) == 3 && parts[0] == "disk" && strings.HasPrefix(parts[1], "disk") &&
		(parts[2] == "in" || parts[2] == "out") {
		// Extract disk name and I/O direction
		diskName := parts[1]
		direction := parts[2]
		if direction == "in" {
			return diskName + " read"
		}
		return diskName + " write"
	}

	// Handle patterns like "gpu.0.temp"
	if len(parts) >= 3 && isNumeric(parts[1]) {
		prefix := strings.ToUpper(parts[0])
		index := parts[1]
		return prefix + " " + index
	}

	// Handle patterns like "gpu.process.0.temp"
	if len(parts) >= 4 && parts[1] == "process" && isNumeric(parts[2]) {
		prefix := strings.ToUpper(parts[0])
		index := parts[2]
		return prefix + " Process " + index
	}

	// Handle patterns like "cpu.0.cpu_percent"
	if len(parts) >= 3 && parts[0] == "cpu" && isNumeric(parts[1]) {
		return "Core " + parts[1]
	}

	// For non-indexed metrics, return a default series name
	return DefaultSystemMetricSeriesName
}

// isNumeric checks if a string is a number.
func isNumeric(s string) bool {
	_, err := strconv.Atoi(s)
	return err == nil
}
