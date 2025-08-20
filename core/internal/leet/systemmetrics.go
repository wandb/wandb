//go:build !wandb_core

package leet

import (
	"regexp"
	"strings"
)

// MetricTemplate represents a system metric configuration.
type MetricTemplate struct {
	Key        string
	YAxis      string
	Regex      *regexp.Regexp
	Percentage bool
	BaseKey    string // For grouping related metrics (e.g., "gpu.temp" for "gpu.0.temp")
	Unit       string
}

// ExtractBaseKey extracts the base metric name for grouping
// e.g., "gpu.0.temp" -> "gpu.temp", "cpu.0.cpu_percent" -> "cpu.cpu_percent"
func ExtractBaseKey(metricName string) string {
	// Pattern to match metrics with numeric indices
	re := regexp.MustCompile(`^(.*?)\.(\d+)\.(.+)$`)
	if matches := re.FindStringSubmatch(metricName); matches != nil {
		return matches[1] + "." + matches[3]
	}
	return metricName
}

// ExtractSeriesName extracts the series identifier from a metric name
// e.g., "gpu.0.temp" -> "GPU 0", "gpu.1.temp" -> "GPU 1"
func ExtractSeriesName(metricName string) string {
	// Pattern to match metrics with numeric indices
	re := regexp.MustCompile(`^(.*?)\.(\d+)\.(.+)$`)
	if matches := re.FindStringSubmatch(metricName); matches != nil {
		prefix := matches[1]
		index := matches[2]

		switch prefix {
		case "gpu":
			return "GPU " + index
		case "cpu":
			return "CPU " + index
		case "tpu":
			return "TPU " + index
		case "ipu":
			return "IPU " + index
		case "trn":
			return "TRN " + index
		default:
			return strings.ToUpper(prefix) + " " + index
		}
	}

	// For non-indexed metrics, return a default series name
	return "Default"
}

// ExtractUnit extracts the unit from the YAxis label
func ExtractUnit(yAxis string) string {
	// Match patterns like (%), (W), (°C), (Bytes), (MB), (GB), (MHz)
	re := regexp.MustCompile(`\(([^)]+)\)`)
	if matches := re.FindStringSubmatch(yAxis); matches != nil {
		return matches[1]
	}
	return ""
}

// MatchMetricTemplate finds the matching template for a given metric name
func MatchMetricTemplate(metricName string, templates map[string]*MetricTemplate) *MetricTemplate {
	// Try exact match first
	if tmpl, exists := templates[metricName]; exists {
		return tmpl
	}

	// Try regex matching
	for _, tmpl := range templates {
		if tmpl.Regex != nil && tmpl.Regex.MatchString(metricName) {
			return tmpl
		}
	}

	// Check if it's an indexed metric and try to match the base pattern
	baseKey := ExtractBaseKey(metricName)
	if baseKey != metricName {
		// It was an indexed metric, try to find a template for the base
		for _, tmpl := range templates {
			if tmpl.Regex != nil && tmpl.Regex.MatchString(baseKey) {
				return tmpl
			}
		}
	}

	return nil
}

// GetSystemMetricTemplates returns all system metric templates
func GetSystemMetricTemplates() map[string]*MetricTemplate {
	templates := map[string]*MetricTemplate{
		// CPU metrics
		"cpu": {
			YAxis:      "Process CPU Utilization (%)",
			Regex:      regexp.MustCompile(`^cpu$`),
			Percentage: true,
		},
		"cpu.cpu_percent": {
			YAxis:      "System CPU Utilization (per core) (%)",
			Regex:      regexp.MustCompile(`^cpu\.\d+\.cpu_percent$`),
			Percentage: true,
		},
		"cpu.ecpu_percent": {
			YAxis:      "Apple eCPU (efficiency cores) Utilization (%)",
			Regex:      regexp.MustCompile(`^cpu\.ecpu_percent$`),
			Percentage: true,
		},
		"cpu.ecpu_freq": {
			YAxis:      "Apple eCPU (efficiency cores) Frequency (MHz)",
			Regex:      regexp.MustCompile(`^cpu\.ecpu_freq$`),
			Percentage: false,
		},
		"cpu.pcpu_percent": {
			YAxis:      "Apple pCPU (performance cores) Utilization (%)",
			Regex:      regexp.MustCompile(`^cpu\.pcpu_percent$`),
			Percentage: true,
		},
		"cpu.pcpu_freq": {
			YAxis:      "Apple pCPU (performance cores) Frequency (MHz)",
			Regex:      regexp.MustCompile(`^cpu\.pcpu_freq$`),
			Percentage: false,
		},
		"cpu.avg_temp": {
			YAxis:      "Average CPU Temperature (°C)",
			Regex:      regexp.MustCompile(`^cpu\.avg_temp$`),
			Percentage: false,
		},
		"cpu.powerWatts": {
			YAxis:      "CPU Power (W)",
			Regex:      regexp.MustCompile(`^cpu\.powerWatts$`),
			Percentage: false,
		},

		// Memory metrics
		"memory_percent": {
			YAxis:      "System Memory Utilization (%)",
			Regex:      regexp.MustCompile(`^memory_percent$`),
			Percentage: true,
		},
		"memory.used": {
			YAxis:      "RAM Used (Bytes)",
			Regex:      regexp.MustCompile(`^memory\.used$`),
			Percentage: false,
		},
		"memory.used_percent": {
			YAxis:      "RAM Used (%)",
			Regex:      regexp.MustCompile(`^memory\.used_percent$`),
			Percentage: true,
		},

		// Swap metrics
		"swap.used": {
			YAxis:      "Swap Memory Used (Bytes)",
			Regex:      regexp.MustCompile(`^swap\.used$`),
			Percentage: false,
		},
		"swap.used_percent": {
			YAxis:      "Swap Memory Used (%)",
			Regex:      regexp.MustCompile(`^swap\.used_percent$`),
			Percentage: true,
		},

		// Process metrics
		"proc.memory.rssMB": {
			YAxis:      "Process Memory In Use (MB)",
			Regex:      regexp.MustCompile(`^proc\.memory\.rssMB$`),
			Percentage: false,
		},
		"proc.memory.percent": {
			YAxis:      "Process Memory In Use (%)",
			Regex:      regexp.MustCompile(`^proc\.memory\.percent$`),
			Percentage: true,
		},
		"proc.memory.availableMB": {
			YAxis:      "Process Memory Available (MB)",
			Regex:      regexp.MustCompile(`^proc\.memory\.availableMB$`),
			Percentage: false,
		},
		"proc.cpu.threads": {
			YAxis:      "Process CPU Threads In Use",
			Regex:      regexp.MustCompile(`^proc\.cpu\.threads$`),
			Percentage: false,
		},

		// Disk metrics
		"disk": {
			YAxis:      "Disk Utilization (%)",
			Regex:      regexp.MustCompile(`^disk$`),
			Percentage: true,
		},
		"disk.usagePercent": {
			YAxis:      "Disk Utilization (%)",
			Regex:      regexp.MustCompile(`^disk\.[^.]+\.usagePercent$`),
			Percentage: true,
		},
		"disk.usageGB": {
			YAxis:      "Disk Utilization (GB)",
			Regex:      regexp.MustCompile(`^disk\.[^.]+\.usageGB$`),
			Percentage: false,
		},
		"disk.in": {
			YAxis:      "Disk Read (MB)",
			Regex:      regexp.MustCompile(`^disk\.in$`),
			Percentage: false,
		},
		"disk.out": {
			YAxis:      "Disk Write (MB)",
			Regex:      regexp.MustCompile(`^disk\.out$`),
			Percentage: false,
		},

		// Network metrics
		"network.recv": {
			YAxis:      "Network Received (Bytes)",
			Regex:      regexp.MustCompile(`^network\.recv$`),
			Percentage: false,
		},
		"network.sent": {
			YAxis:      "Network Sent (Bytes)",
			Regex:      regexp.MustCompile(`^network\.sent$`),
			Percentage: false,
		},

		// System power
		"system.powerWatts": {
			YAxis:      "System Power Usage (W)",
			Regex:      regexp.MustCompile(`^system\.powerWatts$`),
			Percentage: false,
		},

		// GPU metrics (will be grouped by GPU index)
		"gpu.gpu": {
			YAxis:      "GPU Utilization (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.gpu$`),
			Percentage: true,
		},
		"gpu.temp": {
			YAxis:      "GPU Temperature (°C)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.temp$`),
			Percentage: false,
		},
		"gpu.freq": {
			YAxis:      "GPU Frequency (MHz)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.freq$`),
			Percentage: false,
		},
		"gpu.memory": {
			YAxis:      "GPU Time Spent Accessing Memory (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.memory$`),
			Percentage: true,
		},
		"gpu.memoryAllocated": {
			YAxis:      "GPU Memory Allocated (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.memoryAllocated$`),
			Percentage: true,
		},
		"gpu.memoryAllocatedBytes": {
			YAxis:      "GPU Memory Allocated (Bytes)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.memoryAllocatedBytes$`),
			Percentage: false,
		},
		"gpu.memoryUsed": {
			YAxis:      "GPU Memory Used (Bytes)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.memoryUsed$`),
			Percentage: false,
		},
		"gpu.recoveryCount": {
			YAxis:      "GPU Recovery Count",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.recoveryCount$`),
			Percentage: false,
		},
		"gpu.enforcedPowerLimitWatts": {
			YAxis:      "GPU Enforced Power Limit (W)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.enforcedPowerLimitWatts$`),
			Percentage: false,
		},
		"gpu.powerPercent": {
			YAxis:      "GPU Power Usage (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.powerPercent$`),
			Percentage: true,
		},
		"gpu.powerWatts": {
			YAxis:      "GPU Power Usage (W)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.powerWatts$`),
			Percentage: false,
		},
		"gpu.smClock": {
			YAxis:      "GPU Streaming Multiprocessor (SM) Clock Speed (MHz)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.smClock$`),
			Percentage: false,
		},
		"gpu.graphicsClock": {
			YAxis:      "GPU Graphics Clock Speed (MHz)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.graphicsClock$`),
			Percentage: false,
		},
		"gpu.memoryClock": {
			YAxis:      "GPU Memory Clock Speed (MHz)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.memoryClock$`),
			Percentage: false,
		},
		"gpu.correctedMemoryErrors": {
			YAxis:      "GPU Corrected Memory Errors",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.correctedMemoryErrors$`),
			Percentage: false,
		},
		"gpu.uncorrectedMemoryErrors": {
			YAxis:      "GPU Uncorrected Memory Errors",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.uncorrectedMemoryErrors$`),
			Percentage: false,
		},
		"gpu.encoderUtilization": {
			YAxis:      "GPU Encoder Utilization (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.encoderUtilization$`),
			Percentage: true,
		},
		"gpu.smActive": {
			YAxis:      "GPU Streaming Multiprocessor (SM) Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.smActive$`),
			Percentage: true,
		},
		"gpu.smOccupancy": {
			YAxis:      "GPU Streaming Multiprocessor (SM) Occupancy (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.smOccupancy$`),
			Percentage: true,
		},
		"gpu.pipeTensorActive": {
			YAxis:      "GPU Tensor Pipeline Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pipeTensorActive$`),
			Percentage: true,
		},
		"gpu.dramActive": {
			YAxis:      "GPU DRAM Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.dramActive$`),
			Percentage: true,
		},
		"gpu.pipeFp64Active": {
			YAxis:      "GPU FP64 Pipeline Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pipeFp64Active$`),
			Percentage: true,
		},
		"gpu.pipeFp32Active": {
			YAxis:      "GPU FP32 Pipeline Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pipeFp32Active$`),
			Percentage: true,
		},
		"gpu.pipeFp16Active": {
			YAxis:      "GPU FP16 Pipeline Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pipeFp16Active$`),
			Percentage: true,
		},
		"gpu.pipeTensorHmmaActive": {
			YAxis:      "GPU Tensor HMMA Active (%)",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pipeTensorHmmaActive$`),
			Percentage: true,
		},
		"gpu.pcieTxBytes": {
			YAxis:      "GPU PCIe Tx Bytes",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pcieTxBytes$`),
			Percentage: false,
		},
		"gpu.pcieRxBytes": {
			YAxis:      "GPU PCIe Rx Bytes",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.pcieRxBytes$`),
			Percentage: false,
		},
		"gpu.nvlinkTxBytes": {
			YAxis:      "GPU NVLink Tx Bytes",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.nvlinkTxBytes$`),
			Percentage: false,
		},
		"gpu.nvlinkRxBytes": {
			YAxis:      "GPU NVLink Rx Bytes",
			Regex:      regexp.MustCompile(`^gpu\.\d+\.nvlinkRxBytes$`),
			Percentage: false,
		},

		// Process GPU metrics
		"gpu.process.gpu": {
			YAxis:      "Process GPU Utilization (%)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.gpu$`),
			Percentage: true,
		},
		"gpu.process.temp": {
			YAxis:      "Process GPU Temperature (°C)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.temp$`),
			Percentage: false,
		},
		"gpu.process.memory": {
			YAxis:      "Process GPU Time Spent Accessing Memory (%)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.memory$`),
			Percentage: true,
		},
		"gpu.process.memoryAllocated": {
			YAxis:      "Process GPU Memory Allocated (%)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocated$`),
			Percentage: true,
		},
		"gpu.process.memoryAllocatedBytes": {
			YAxis:      "Process GPU Memory Allocated (Bytes)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.memoryAllocatedBytes$`),
			Percentage: false,
		},
		"gpu.process.memoryUsedBytes": {
			YAxis:      "Process GPU Memory Used (Bytes)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.memoryUsedBytes$`),
			Percentage: false,
		},
		"gpu.process.enforcedPowerLimitWatts": {
			YAxis:      "Process GPU Enforced Power Limit (W)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.enforcedPowerLimitWatts$`),
			Percentage: false,
		},
		"gpu.process.powerPercent": {
			YAxis:      "Process GPU Power Usage (%)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.powerPercent$`),
			Percentage: true,
		},
		"gpu.process.powerWatts": {
			YAxis:      "Process GPU Power Usage (W)",
			Regex:      regexp.MustCompile(`^gpu\.process\.\d+\.powerWatts$`),
			Percentage: false,
		},

		// Apple Neural Engine
		"ane.power": {
			YAxis:      "Apple Neural Engine Power (W)",
			Regex:      regexp.MustCompile(`^ane\.power$`),
			Percentage: false,
		},

		// TPU metrics
		"tpu.dutyCycle": {
			YAxis:      "TPU Duty Cycle (%)",
			Regex:      regexp.MustCompile(`^tpu\.\d+\.dutyCycle$`),
			Percentage: true,
		},
		"tpu.memoryUsage": {
			YAxis:      "TPU Memory Usage (%)",
			Regex:      regexp.MustCompile(`^tpu\.\d+\.memoryUsage$`),
			Percentage: true,
		},
		"tpu.memoryUsageBytes": {
			YAxis:      "TPU Memory Usage (Bytes)",
			Regex:      regexp.MustCompile(`^tpu\.\d+\.memoryUsageBytes$`),
			Percentage: false,
		},

		// IPU metrics
		"ipu.averageBoardTemp": {
			YAxis:      "IPU Average Board Temperature (°C)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.average board temp$`),
			Percentage: false,
		},
		"ipu.averageDieTemp": {
			YAxis:      "IPU Average Die Temperature (°C)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.average die temp$`),
			Percentage: false,
		},
		"ipu.clock": {
			YAxis:      "IPU Clock (MHz)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.clock$`),
			Percentage: false,
		},
		"ipu.ipuPower": {
			YAxis:      "IPU Power (W)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.ipu power$`),
			Percentage: false,
		},
		"ipu.ipuUtilisation": {
			YAxis:      "IPU Utilization (%)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(%\)$`),
			Percentage: true,
		},
		"ipu.ipuUtilisationSession": {
			YAxis:      "IPU Utilization (session) (%)",
			Regex:      regexp.MustCompile(`^ipu\.\d+\.ipu utilisation \(session\)$`),
			Percentage: true,
		},

		// Trainium metrics
		"trn.neuroncore_utilization": {
			YAxis:      "Trainium Neuron Core Utilization (%)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_utilization$`),
			Percentage: true,
		},
		"trn.host_total_memory_usage": {
			YAxis:      "Trainium Host Memory Usage, total (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.host_total_memory_usage$`),
			Percentage: false,
		},
		"trn.neuron_device_total_memory_usage": {
			YAxis:      "Trainium Neuron Device Memory Usage, total (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.neuron_device_total_memory_usage$`),
			Percentage: false,
		},
		"trn.host_memory_usage.application_memory": {
			YAxis:      "Trainium Host Memory Usage, application memory (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.host_memory_usage\.application_memory$`),
			Percentage: false,
		},
		"trn.host_memory_usage.constants": {
			YAxis:      "Trainium Host Memory Usage, constants (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.host_memory_usage\.constants$`),
			Percentage: false,
		},
		"trn.host_memory_usage.dma_buffers": {
			YAxis:      "Trainium Host Memory Usage, DMA buffers (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.host_memory_usage\.dma_buffers$`),
			Percentage: false,
		},
		"trn.host_memory_usage.tensors": {
			YAxis:      "Trainium Host Memory Usage, tensors (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.host_memory_usage\.tensors$`),
			Percentage: false,
		},
		"trn.neuroncore_memory_usage.constants": {
			YAxis:      "Trainium Neuron Device Memory Usage, constants (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.constants$`),
			Percentage: false,
		},
		"trn.neuroncore_memory_usage.model_code": {
			YAxis:      "Trainium Neuron Device Memory Usage, model code (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_code$`),
			Percentage: false,
		},
		"trn.neuroncore_memory_usage.model_shared_scratchpad": {
			YAxis:      "Trainium Neuron Device Memory Usage, model shared scratchpad (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.model_shared_scratchpad$`),
			Percentage: false,
		},
		"trn.neuroncore_memory_usage.runtime_memory": {
			YAxis:      "Trainium Neuron Device Memory Usage, runtime_memory (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.runtime_memory$`),
			Percentage: false,
		},
		"trn.neuroncore_memory_usage.tensors": {
			YAxis:      "Trainium Neuron Device Memory Usage, tensors (Bytes)",
			Regex:      regexp.MustCompile(`^trn\.\d+\.neuroncore_memory_usage\.tensors$`),
			Percentage: false,
		},
	}

	// Fill in derived fields
	for key, tmpl := range templates {
		tmpl.Key = key
		tmpl.Unit = ExtractUnit(tmpl.YAxis)
		tmpl.BaseKey = ExtractBaseKey(key)
	}

	return templates
}
