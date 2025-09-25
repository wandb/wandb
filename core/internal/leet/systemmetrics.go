package leet

import (
	"regexp"
	"strconv"
	"strings"
)

// MetricDef represents a simplified system metric definition.
type MetricDef struct {
	Title      string         // Display title (without unit)
	Unit       string         // Unit: "%", "°C", "W", "MB", etc.
	MinY       float64        // Default min Y value
	MaxY       float64        // Default max Y value
	Percentage bool           // Whether this is a percentage metric
	AutoRange  bool           // Whether to auto-adjust Y range based on data
	Regex      *regexp.Regexp // Pattern to match metric names (including suffixes)
}

// metricDefs holds all metric definitions.
//
// Patterns are ordered from most specific to least specific for proper matching.
var metricDefs = []MetricDef{
	// CPU metrics
	{Title: "Process CPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu(\/l:.+)?$`)},
	{Title: "CPU Core", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.\d+\.cpu_percent(\/l:.+)?$`)},
	{Title: "Apple E-cores", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.ecpu_percent(\/l:.+)?$`)},
	{Title: "Apple E-cores Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.ecpu_freq(\/l:.+)?$`)},
	{Title: "Apple P-cores", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^cpu\.pcpu_percent(\/l:.+)?$`)},
	{Title: "Apple P-cores Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.pcpu_freq(\/l:.+)?$`)},
	{Title: "CPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.avg_temp(\/l:.+)?$`)},
	{Title: "CPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^cpu\.powerWatts(\/l:.+)?$`)},

	// Memory metrics
	{Title: "System Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^memory_percent(\/l:.+)?$`)},
	{Title: "RAM Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^memory\.used(\/l:.+)?$`)},
	{Title: "RAM Used", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^memory\.used_percent(\/l:.+)?$`)},

	// Swap metrics
	{Title: "Swap Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^swap\.used(\/l:.+)?$`)},
	{Title: "Swap Used", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^swap\.used_percent(\/l:.+)?$`)},

	// Process metrics
	{Title: "Process Memory", Unit: "MB", MinY: 0, MaxY: 32768, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.memory\.rssMB(\/l:.+)?$`)},
	{Title: "Process Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^proc\.memory\.percent(\/l:.+)?$`)},
	{Title: "Process Memory Available", Unit: "MB", MinY: 0, MaxY: 32768, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.memory\.availableMB(\/l:.+)?$`)},
	{Title: "Process CPU Threads", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^proc\.cpu\.threads(\/l:.+)?$`)},

	// Disk metrics - handle both aggregated and per-device
	{Title: "Disk", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^disk$`)},
	{Title: "Disk", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.usagePercent(\/l:.+)?$`)},
	{Title: "Disk", Unit: "GB", MinY: 0, MaxY: 1000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.usageGB(\/l:.+)?$`)},
	// Per-device I/O patterns (e.g., disk.disk4.in, disk.disk1.out) - CUMULATIVE
	{Title: "Disk I/O Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.[^.]+\.(in|out)(\/l:.+)?$`)},
	// Aggregated I/O patterns - CUMULATIVE
	{Title: "Disk Read Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.in(\/l:.+)?$`)},
	{Title: "Disk Write Total", Unit: "MB", MinY: 0, MaxY: 10000, AutoRange: true,
		Regex: regexp.MustCompile(`^disk\.out(\/l:.+)?$`)},

	// Network metrics - treat as rates instead of cumulative
	{Title: "Network Rx", Unit: "B", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^network\.recv(\/l:.+)?$`)},
	{Title: "Network Tx", Unit: "B", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^network\.sent(\/l:.+)?$`)},

	// System power
	{Title: "System Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^system\.powerWatts(\/l:.+)?$`)},

	// Apple Neural Engine
	{Title: "Neural Engine Power", Unit: "W", MinY: 0, MaxY: 50, AutoRange: true,
		Regex: regexp.MustCompile(`^ane\.power(\/l:.+)?$`)},

	// GPU metrics
	{Title: "GPU Utilization", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.gpu(\/l:.+)?$`)},
	{Title: "GPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.temp(\/l:.+)?$`)},
	{Title: "GPU Freq", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.freq(\/l:.+)?$`)},
	{Title: "GPU Memory Access", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memory(\/l:.+)?$`)},
	{Title: "GPU Memory Allocated", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryAllocated(\/l:.+)?$`)},
	{Title: "GPU Memory Allocated", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryAllocatedBytes(\/l:.+)?$`)},
	{Title: "GPU Memory Used", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryUsed(\/l:.+)?$`)},
	{Title: "GPU Recovery Count", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.recoveryCount(\/l:.+)?$`)},
	{Title: "GPU Power Limit", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.enforcedPowerLimitWatts(\/l:.+)?$`)},
	{Title: "GPU Power", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.powerPercent(\/l:.+)?$`)},
	{Title: "GPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.powerWatts(\/l:.+)?$`)},
	{Title: "GPU SM Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smClock(\/l:.+)?$`)},
	{Title: "GPU Graphics Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.graphicsClock(\/l:.+)?$`)},
	{Title: "GPU Memory Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.memoryClock(\/l:.+)?$`)},
	{Title: "GPU Corrected Errors", Unit: "", MinY: 0, MaxY: 1000, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.correctedMemoryErrors(\/l:.+)?$`)},
	{Title: "GPU Uncorrected Errors", Unit: "", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.uncorrectedMemoryErrors(\/l:.+)?$`)},
	{Title: "GPU Encoder", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.encoderUtilization(\/l:.+)?$`)},
	{Title: "GPU SM Active", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smActive(\/l:.+)?$`)},
	{Title: "GPU SM Occupancy", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.smOccupancy(\/l:.+)?$`)},
	{Title: "GPU Tensor Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeTensorActive(\/l:.+)?$`)},
	{Title: "GPU DRAM Active", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.dramActive(\/l:.+)?$`)},
	{Title: "GPU FP64 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp64Active(\/l:.+)?$`)},
	{Title: "GPU FP32 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp32Active(\/l:.+)?$`)},
	{Title: "GPU FP16 Pipeline", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeFp16Active(\/l:.+)?$`)},
	{Title: "GPU Tensor HMMA", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pipeTensorHmmaActive(\/l:.+)?$`)},
	{Title: "GPU PCIe Tx", Unit: "GB/s", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pcieTxBytes(\/l:.+)?$`)},
	{Title: "GPU PCIe Rx", Unit: "GB/s", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.pcieRxBytes(\/l:.+)?$`)},
	{Title: "GPU NVLink Tx", Unit: "GB/s", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.nvlinkTxBytes(\/l:.+)?$`)},
	{Title: "GPU NVLink Rx", Unit: "GB/s", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.\d+\.nvlinkRxBytes(\/l:.+)?$`)},

	// Process GPU metrics
	{Title: "Process GPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.gpu(\/l:.+)?$`)},
	{Title: "Process GPU Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.temp(\/l:.+)?$`)},
	{Title: "Process GPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memory(\/l:.+)?$`)},
	{Title: "Process GPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocated(\/l:.+)?$`)},
	{Title: "Process GPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocatedBytes(\/l:.+)?$`)},
	{Title: "Process GPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.memoryUsedBytes(\/l:.+)?$`)},
	{Title: "Process GPU Power Limit", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.enforcedPowerLimitWatts(\/l:.+)?$`)},
	{Title: "Process GPU Power", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.powerPercent(\/l:.+)?$`)},
	{Title: "Process GPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^gpu\.process\.\d+\.powerWatts(\/l:.+)?$`)},

	// TPU metrics
	{Title: "TPU Duty Cycle", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.dutyCycle(\/l:.+)?$`)},
	{Title: "TPU Memory", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.memory[Uu]sage(\/l:.+)?$`)},
	{Title: "TPU Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^tpu\.\d+\.memory[Uu]sage[Bb]ytes(\/l:.+)?$`)},

	// IPU metrics
	{Title: "IPU Board Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.average board temp(\/l:.+)?$`)},
	{Title: "IPU Die Temp", Unit: "°C", MinY: 0, MaxY: 100, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.average die temp(\/l:.+)?$`)},
	{Title: "IPU Clock", Unit: "MHz", MinY: 0, MaxY: 3000, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.clock(\/l:.+)?$`)},
	{Title: "IPU Power", Unit: "W", MinY: 0, MaxY: 500, AutoRange: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu power(\/l:.+)?$`)},
	{Title: "IPU", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(%\)(\/l:.+)?$`)},
	{Title: "IPU Session", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(session\)(\/l:.+)?$`)},

	// Trainium metrics
	{Title: "Neuron Core", Unit: "%", MinY: 0, MaxY: 100, Percentage: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_utilization(\/l:.+)?$`)},
	{Title: "Trainium Host Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_total_memory_usage(\/l:.+)?$`)},
	{Title: "Neuron Device Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.neuron_device_total_memory_usage(\/l:.+)?$`)},
	{Title: "Trainium Host App Memory", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.application_memory(\/l:.+)?$`)},
	{Title: "Trainium Host Constants", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.constants(\/l:.+)?$`)},
	{Title: "Trainium Host DMA", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.dma_buffers(\/l:.+)?$`)},
	{Title: "Trainium Host Tensors", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.host_memory_usage\.tensors(\/l:.+)?$`)},
	{Title: "Neuron Constants", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.constants(\/l:.+)?$`)},
	{Title: "Neuron Model Code", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_code(\/l:.+)?$`)},
	{Title: "Neuron Scratchpad", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_shared_scratchpad(\/l:.+)?$`)},
	{Title: "Neuron Runtime", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
		Regex: regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.runtime_memory(\/l:.+)?$`)},
	{Title: "Neuron Tensors", Unit: "GB", MinY: 0, MaxY: 32, AutoRange: true,
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
	return "Default"
}

// isNumeric checks if a string is a number.
func isNumeric(s string) bool {
	_, err := strconv.Atoi(s)
	return err == nil
}
