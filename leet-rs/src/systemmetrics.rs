//! System metric definitions: chart grouping, units, and Y ranges.

use std::sync::LazyLock;

use regex::Regex;

use crate::units::{
    UNIT_BYTES, UNIT_CELSIUS, UNIT_GIB, UNIT_GIBPS, UNIT_MHZ, UNIT_MIB, UNIT_PERCENT, UNIT_SCALAR,
    UNIT_WATT, Unit,
};

pub const DEFAULT_SYSTEM_METRIC_SERIES_NAME: &str = "Default";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum MetricChartKind {
    #[default]
    Line,
    FrenchFries,
}

/// A system metric definition needed for displaying it on a chart.
pub struct MetricDef {
    pub name: &'static str,
    pub unit: Unit,
    /// Default min Y value.
    pub min_y: f64,
    /// Default max Y value.
    pub max_y: f64,
    /// Whether this is a percentage metric.
    pub percentage: bool,
    /// Whether to auto-adjust the Y range based on data.
    pub auto_range: bool,
    pub chart_kind: MetricChartKind,
    /// Pattern to match metric names (including suffixes).
    pub regex: Regex,
}

impl MetricDef {
    /// The title to display on the metric chart.
    pub fn title(&self) -> String {
        if self.unit.name().is_empty() {
            return self.name.to_string();
        }
        format!("{} ({})", self.name, self.unit.name())
    }
}

struct DefSpec {
    name: &'static str,
    unit: Unit,
    min_y: f64,
    max_y: f64,
    percentage: bool,
    auto_range: bool,
    pattern: &'static str,
}

const fn pct(name: &'static str, pattern: &'static str) -> DefSpec {
    DefSpec {
        name,
        unit: UNIT_PERCENT,
        min_y: 0.0,
        max_y: 100.0,
        percentage: true,
        auto_range: false,
        pattern,
    }
}

const fn auto(name: &'static str, unit: Unit, max_y: f64, pattern: &'static str) -> DefSpec {
    DefSpec {
        name,
        unit,
        min_y: 0.0,
        max_y,
        percentage: false,
        auto_range: true,
        pattern,
    }
}

/// All metric definitions, ordered from most specific to least specific for
/// proper matching.
#[rustfmt::skip]
static DEF_SPECS: &[DefSpec] = &[
    // CPU metrics.
    pct("Process CPU", r"^cpu(/l:.+)?$"),
    pct("CPU Core", r"^cpu\.\d+\.cpu_percent(/l:.+)?$"),
    pct("Apple E-cores", r"^cpu\.ecpu_percent(/l:.+)?$"),
    auto("Apple E-cores Freq", UNIT_MHZ, 3000.0, r"^cpu\.ecpu_freq(/l:.+)?$"),
    pct("Apple P-cores", r"^cpu\.pcpu_percent(/l:.+)?$"),
    auto("Apple P-cores Freq", UNIT_MHZ, 3000.0, r"^cpu\.pcpu_freq(/l:.+)?$"),
    auto("CPU Temp", UNIT_CELSIUS, 100.0, r"^cpu\.avg_temp(/l:.+)?$"),
    auto("CPU Power", UNIT_WATT, 500.0, r"^cpu\.powerWatts(/l:.+)?$"),

    // Memory metrics.
    pct("System Memory", r"^memory_percent(/l:.+)?$"),
    auto("RAM Used", UNIT_BYTES, 32.0, r"^memory\.used(/l:.+)?$"),
    pct("RAM Used", r"^memory\.used_percent(/l:.+)?$"),

    // Swap metrics.
    auto("Swap Used", UNIT_BYTES, 32.0, r"^swap\.used(/l:.+)?$"),
    pct("Swap Used", r"^swap\.used_percent(/l:.+)?$"),

    // Process metrics.
    auto("Process Memory", UNIT_MIB, 32768.0, r"^proc\.memory\.rssMB(/l:.+)?$"),
    pct("Process Memory", r"^proc\.memory\.percent(/l:.+)?$"),
    auto("Process Memory Available", UNIT_MIB, 32768.0, r"^proc\.memory\.availableMB(/l:.+)?$"),
    auto("Process CPU Threads", UNIT_SCALAR, 100.0, r"^proc\.cpu\.threads(/l:.+)?$"),

    // Disk metrics - handle both aggregated and per-device.
    pct("Disk", r"^disk$"),
    pct("Disk", r"^disk\.[^.]+\.usagePercent(/l:.+)?$"),
    auto("Disk", UNIT_GIB, 1000.0, r"^disk\.[^.]+\.usageGB(/l:.+)?$"),
    // Per-device I/O patterns (e.g., disk.disk4.in) - CUMULATIVE.
    auto("Disk I/O Total", UNIT_MIB, 10000.0, r"^disk\.[^.]+\.(in|out)(/l:.+)?$"),
    // Aggregated I/O patterns - CUMULATIVE.
    auto("Disk Read Total", UNIT_MIB, 10000.0, r"^disk\.in(/l:.+)?$"),
    auto("Disk Write Total", UNIT_MIB, 10000.0, r"^disk\.out(/l:.+)?$"),

    // Network metrics - treat as rates instead of cumulative.
    auto("Network Rx", UNIT_BYTES, 100.0, r"^network\.recv(/l:.+)?$"),
    auto("Network Tx", UNIT_BYTES, 100.0, r"^network\.sent(/l:.+)?$"),

    // System power.
    auto("System Power", UNIT_WATT, 500.0, r"^system\.powerWatts(/l:.+)?$"),

    // Apple Neural Engine.
    auto("Neural Engine Power", UNIT_WATT, 50.0, r"^ane\.power(/l:.+)?$"),

    // GPU metrics.
    pct("GPU Utilization", r"^gpu\.\d+\.gpu(/l:.+)?$"),
    auto("GPU Temp", UNIT_CELSIUS, 100.0, r"^gpu\.\d+\.temp(/l:.+)?$"),
    auto("GPU Freq", UNIT_MHZ, 3000.0, r"^gpu\.\d+\.freq(/l:.+)?$"),
    pct("GPU Memory Access", r"^gpu\.\d+\.memory(/l:.+)?$"),
    pct("GPU Memory Allocated", r"^gpu\.\d+\.memoryAllocated(/l:.+)?$"),
    auto("GPU Memory Allocated", UNIT_BYTES, 32.0, r"^gpu\.\d+\.memoryAllocatedBytes(/l:.+)?$"),
    auto("GPU Memory Used", UNIT_BYTES, 32.0, r"^gpu\.\d+\.memoryUsed(/l:.+)?$"),
    auto("GPU Recovery Count", UNIT_SCALAR, 100.0, r"^gpu\.\d+\.recoveryCount(/l:.+)?$"),
    auto("GPU Power Limit", UNIT_WATT, 500.0, r"^gpu\.\d+\.enforcedPowerLimitWatts(/l:.+)?$"),
    pct("GPU Power", r"^gpu\.\d+\.powerPercent(/l:.+)?$"),
    auto("GPU Power", UNIT_WATT, 500.0, r"^gpu\.\d+\.powerWatts(/l:.+)?$"),
    auto("GPU SM Clock", UNIT_MHZ, 3000.0, r"^gpu\.\d+\.smClock(/l:.+)?$"),
    auto("GPU Graphics Clock", UNIT_MHZ, 3000.0, r"^gpu\.\d+\.graphicsClock(/l:.+)?$"),
    auto("GPU Memory Clock", UNIT_MHZ, 3000.0, r"^gpu\.\d+\.memoryClock(/l:.+)?$"),
    auto("GPU Corrected Errors", UNIT_SCALAR, 1000.0, r"^gpu\.\d+\.correctedMemoryErrors(/l:.+)?$"),
    auto("GPU Uncorrected Errors", UNIT_SCALAR, 100.0, r"^gpu\.\d+\.uncorrectedMemoryErrors(/l:.+)?$"),
    pct("GPU Encoder", r"^gpu\.\d+\.encoderUtilization(/l:.+)?$"),
    pct("GPU SM Active", r"^gpu\.\d+\.smActive(/l:.+)?$"),
    pct("GPU SM Occupancy", r"^gpu\.\d+\.smOccupancy(/l:.+)?$"),
    pct("GPU Tensor Pipeline", r"^gpu\.\d+\.pipeTensorActive(/l:.+)?$"),
    pct("GPU DRAM Active", r"^gpu\.\d+\.dramActive(/l:.+)?$"),
    pct("GPU FP64 Pipeline", r"^gpu\.\d+\.pipeFp64Active(/l:.+)?$"),
    pct("GPU FP32 Pipeline", r"^gpu\.\d+\.pipeFp32Active(/l:.+)?$"),
    pct("GPU FP16 Pipeline", r"^gpu\.\d+\.pipeFp16Active(/l:.+)?$"),
    pct("GPU Tensor HMMA", r"^gpu\.\d+\.pipeTensorHmmaActive(/l:.+)?$"),
    auto("GPU PCIe Tx", UNIT_GIBPS, 32.0, r"^gpu\.\d+\.pcieTxBytes(/l:.+)?$"),
    auto("GPU PCIe Rx", UNIT_GIBPS, 32.0, r"^gpu\.\d+\.pcieRxBytes(/l:.+)?$"),
    auto("GPU NVLink Tx", UNIT_GIBPS, 100.0, r"^gpu\.\d+\.nvlinkTxBytes(/l:.+)?$"),
    auto("GPU NVLink Rx", UNIT_GIBPS, 100.0, r"^gpu\.\d+\.nvlinkRxBytes(/l:.+)?$"),

    // Per-process GPU metrics.
    pct("Process GPU", r"^gpu\.process\.\d+\.gpu(/l:.+)?$"),
    auto("Process GPU Temp", UNIT_CELSIUS, 100.0, r"^gpu\.process\.\d+\.temp(/l:.+)?$"),
    pct("Process GPU Memory", r"^gpu\.process\.\d+\.memory(/l:.+)?$"),
    pct("Process GPU Memory", r"^gpu\.process\.\d+\.memoryAllocated(/l:.+)?$"),
    auto("Process GPU Memory", UNIT_BYTES, 32.0, r"^gpu\.process\.\d+\.memoryAllocatedBytes(/l:.+)?$"),
    auto("Process GPU Memory", UNIT_BYTES, 32.0, r"^gpu\.process\.\d+\.memoryUsedBytes(/l:.+)?$"),
    auto("Process GPU Power Limit", UNIT_WATT, 500.0, r"^gpu\.process\.\d+\.enforcedPowerLimitWatts(/l:.+)?$"),
    pct("Process GPU Power", r"^gpu\.process\.\d+\.powerPercent(/l:.+)?$"),
    auto("Process GPU Power", UNIT_WATT, 500.0, r"^gpu\.process\.\d+\.powerWatts(/l:.+)?$"),

    // TPU metrics — per-device gauges.
    pct("TPU Tensorcore Utilization", r"^tpu\.\d+\.tensorcoreUtilization(/l:.+)?$"),
    auto("TPU Tensorcore Idle Duration", UNIT_SCALAR, 100.0, r"^tpu\.\d+\.tensorcoreIdleDuration(/l:.+)?$"),
    pct("TPU Duty Cycle", r"^tpu\.\d+\.dutyCycle(/l:.+)?$"),
    auto("TPU HBM Capacity Total", UNIT_BYTES, 32.0, r"^tpu\.\d+\.hbmCapacityTotal(/l:.+)?$"),
    auto("TPU HBM Capacity Usage", UNIT_BYTES, 32.0, r"^tpu\.\d+\.hbmCapacityUsage(/l:.+)?$"),
    pct("TPU Runtime HBM Utilization", r"^tpu\.\d+\.runtimeHbmUtilization(/l:.+)?$"),
    pct("TPU HBM Memory Usage", r"^tpu\.\d+\.hbmMemoryUsage(/l:.+)?$"),
    // TPU metrics — latency distributions (labeled: .label.statUs).
    auto("TPU Buffer Transfer Latency", UNIT_SCALAR, 10000.0, r"^tpu\.bufferTransferLatency\..+$"),
    auto("TPU Inbound Buffer Transfer Latency", UNIT_SCALAR, 10000.0, r"^tpu\.inboundBufferTransferLatency\..+$"),
    auto("TPU Host-to-Device Latency", UNIT_SCALAR, 10000.0, r"^tpu\.hostToDeviceTransferLatency\..+$"),
    auto("TPU Device-to-Host Latency", UNIT_SCALAR, 10000.0, r"^tpu\.deviceToHostTransferLatency\..+$"),
    auto("TPU Collective E2E Latency", UNIT_SCALAR, 10000.0, r"^tpu\.collectiveE2ELatency\..+$"),
    auto("TPU Host Compute Latency", UNIT_SCALAR, 10000.0, r"^tpu\.hostComputeLatency\..+$"),
    auto("TPU HLO Exec Timing", UNIT_SCALAR, 10000.0, r"^tpu\.hloExecTiming\..+$"),
    // TPU metrics — flat distributions.
    auto("TPU gRPC TCP Min RTT", UNIT_SCALAR, 10000.0, r"^tpu\.grpcTcpMinRtt\..+$"),
    auto("TPU gRPC TCP Delivery Rate", UNIT_SCALAR, 10000.0, r"^tpu\.grpcTcpDeliveryRate\..+$"),
    // TPU metrics — HLO queue size (colon-keyed: .label).
    auto("TPU HLO Queue Size", UNIT_SCALAR, 100.0, r"^tpu\.hloQueueSize\..+$"),
    // TPU metrics — SDK-only gauges.
    auto("TPU ICI Link Health", UNIT_SCALAR, 1.0, r"^tpu\.\d+\.iciLinkHealth(/l:.+)?$"),
    auto("TPU Throttle Score", UNIT_SCALAR, 100.0, r"^tpu\.\d+\.throttleScore(/l:.+)?$"),

    // IPU metrics.
    auto("IPU Board Temp", UNIT_CELSIUS, 100.0, r"^ipu\.\d+\.average board temp(/l:.+)?$"),
    auto("IPU Die Temp", UNIT_CELSIUS, 100.0, r"^ipu\.\d+\.average die temp(/l:.+)?$"),
    auto("IPU Clock", UNIT_MHZ, 3000.0, r"^ipu\.\d+\.clock(/l:.+)?$"),
    auto("IPU Power", UNIT_WATT, 500.0, r"^ipu\.\d+\.ipu power(/l:.+)?$"),
    pct("IPU", r"^ipu\.\d+\.ipu utilisation \(%\)(/l:.+)?$"),
    pct("IPU Session", r"^ipu\.\d+\.ipu utilisation \(session\)(/l:.+)?$"),

    // Trainium metrics.
    pct("Neuron Core", r"^trn\.\d+\.neuroncore_utilization(/l:.+)?$"),
    auto("Trainium Host Memory", UNIT_GIB, 32.0, r"^trn\.host_total_memory_usage(/l:.+)?$"),
    auto("Neuron Device Memory", UNIT_GIB, 32.0, r"^trn\.neuron_device_total_memory_usage(/l:.+)?$"),
    auto("Trainium Host App Memory", UNIT_GIB, 32.0, r"^trn\.host_memory_usage\.application_memory(/l:.+)?$"),
    auto("Trainium Host Constants", UNIT_GIB, 32.0, r"^trn\.host_memory_usage\.constants(/l:.+)?$"),
    auto("Trainium Host DMA", UNIT_GIB, 32.0, r"^trn\.host_memory_usage\.dma_buffers(/l:.+)?$"),
    auto("Trainium Host Tensors", UNIT_GIB, 32.0, r"^trn\.host_memory_usage\.tensors(/l:.+)?$"),
    auto("Neuron Constants", UNIT_GIB, 32.0, r"^trn\.\d+\.neuroncore_memory_usage\.constants(/l:.+)?$"),
    auto("Neuron Model Code", UNIT_GIB, 32.0, r"^trn\.\d+\.neuroncore_memory_usage\.model_code(/l:.+)?$"),
    auto("Neuron Scratchpad", UNIT_GIB, 32.0, r"^trn\.\d+\.neuroncore_memory_usage\.model_shared_scratchpad(/l:.+)?$"),
    auto("Neuron Runtime", UNIT_GIB, 32.0, r"^trn\.\d+\.neuroncore_memory_usage\.runtime_memory(/l:.+)?$"),
    auto("Neuron Tensors", UNIT_GIB, 32.0, r"^trn\.\d+\.neuroncore_memory_usage\.tensors(/l:.+)?$"),
];

/// Compiled metric definitions.
pub static METRIC_DEFS: LazyLock<Vec<MetricDef>> = LazyLock::new(|| {
    DEF_SPECS
        .iter()
        .map(|s| MetricDef {
            name: s.name,
            unit: s.unit,
            min_y: s.min_y,
            max_y: s.max_y,
            percentage: s.percentage,
            auto_range: s.auto_range,
            chart_kind: MetricChartKind::Line,
            regex: Regex::new(s.pattern).expect("static metric pattern"),
        })
        .collect()
});

/// Finds the matching definition for a given metric name.
pub fn match_metric_def(metric_name: &str) -> Option<&'static MetricDef> {
    // Remove any prefix slashes if present.
    let metric_name = metric_name.strip_prefix('/').unwrap_or(metric_name);

    // Try each pattern in order (most specific first).
    METRIC_DEFS.iter().find(|d| d.regex.is_match(metric_name))
}

fn is_numeric(s: &str) -> bool {
    !s.is_empty() && s.parse::<i64>().is_ok()
}

/// Strips the shared-mode label suffix ("/l:...") if present.
fn strip_label_suffix(metric_name: &str) -> &str {
    match metric_name.find("/l:") {
        Some(idx) if idx > 0 => &metric_name[..idx],
        _ => metric_name,
    }
}

/// Extracts the base metric name for grouping.
///
/// For example, "gpu.0.temp" -> "gpu.temp", "disk.disk4.in" ->
/// "disk.io_per_device" (special case for disk I/O).
pub fn extract_base_key(metric_name: &str) -> String {
    let metric_name = strip_label_suffix(metric_name);
    let parts: Vec<&str> = metric_name.split('.').collect();

    // Special handling for disk I/O metrics:
    // disk.{device}.in/out -> disk.io_per_device.
    if parts.len() == 3 && parts[0] == "disk" && (parts[2] == "in" || parts[2] == "out") {
        return "disk.io_per_device".to_string();
    }

    // Handle patterns like "gpu.0.temp" -> "gpu.temp".
    if parts.len() >= 3 && is_numeric(parts[1]) {
        return format!("{}.{}", parts[0], parts[2..].join("."));
    }

    // Handle patterns like "gpu.process.0.temp" -> "gpu.process.temp".
    if parts.len() >= 4 && parts[1] == "process" && is_numeric(parts[2]) {
        return format!("{}.{}.{}", parts[0], parts[1], parts[3..].join("."));
    }

    // Handle TPU non-per-device patterns like
    // "tpu.hloExecTiming.tensor_core_0.meanUs" -> "tpu.hloExecTiming".
    if parts.len() >= 3 && parts[0] == "tpu" && !is_numeric(parts[1]) {
        return format!("{}.{}", parts[0], parts[1]);
    }

    metric_name.to_string()
}

/// Extracts the series identifier from a metric name.
/// E.g., "gpu.0.temp" -> "GPU 0", "disk.disk4.in" -> "disk4 read".
pub fn extract_series_name(metric_name: &str) -> String {
    let metric_name = strip_label_suffix(metric_name);
    let parts: Vec<&str> = metric_name.split('.').collect();

    // Handle disk I/O patterns like "disk.disk4.in", "disk.nvme0n1.out".
    if parts.len() == 3 && parts[0] == "disk" && (parts[2] == "in" || parts[2] == "out") {
        let direction = if parts[2] == "in" { "read" } else { "write" };
        return format!("{} {}", parts[1], direction);
    }

    // Handle patterns like "gpu.0.temp" (also covers "cpu.0.cpu_percent",
    // matching the Go implementation's branch order).
    if parts.len() >= 3 && is_numeric(parts[1]) {
        return format!("{} {}", parts[0].to_uppercase(), parts[1]);
    }

    // Handle patterns like "gpu.process.0.temp".
    if parts.len() >= 4 && parts[1] == "process" && is_numeric(parts[2]) {
        return format!("{} Process {}", parts[0].to_uppercase(), parts[2]);
    }

    // Handle TPU non-per-device patterns like
    // "tpu.hloExecTiming.tensor_core_0.meanUs" -> "tensor_core_0 meanUs".
    if parts.len() >= 3 && parts[0] == "tpu" && !is_numeric(parts[1]) {
        return parts[2..].join(" ");
    }

    // For non-indexed metrics, return a default series name.
    DEFAULT_SYSTEM_METRIC_SERIES_NAME.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn match_defs() {
        assert_eq!(match_metric_def("cpu").unwrap().name, "Process CPU");
        assert_eq!(match_metric_def("gpu.0.temp").unwrap().name, "GPU Temp");
        assert_eq!(
            match_metric_def("gpu.1.powerWatts/l:node0").unwrap().name,
            "GPU Power"
        );
        assert_eq!(
            match_metric_def("memory_percent").unwrap().name,
            "System Memory"
        );
        assert!(match_metric_def("bogus.metric").is_none());
    }

    #[test]
    fn base_keys() {
        assert_eq!(extract_base_key("gpu.0.temp"), "gpu.temp");
        assert_eq!(extract_base_key("cpu.0.cpu_percent"), "cpu.cpu_percent");
        assert_eq!(extract_base_key("disk.disk4.in"), "disk.io_per_device");
        assert_eq!(extract_base_key("gpu.process.0.temp"), "gpu.process.temp");
        assert_eq!(
            extract_base_key("tpu.hloQueueSize.tensor_core_0"),
            "tpu.hloQueueSize"
        );
        assert_eq!(extract_base_key("memory_percent"), "memory_percent");
        assert_eq!(extract_base_key("gpu.0.temp/l:node0"), "gpu.temp");
    }

    #[test]
    fn series_names() {
        assert_eq!(extract_series_name("gpu.0.temp"), "GPU 0");
        assert_eq!(extract_series_name("cpu.3.cpu_percent"), "CPU 3");
        assert_eq!(extract_series_name("disk.disk4.in"), "disk4 read");
        assert_eq!(extract_series_name("disk.nvme0n1.out"), "nvme0n1 write");
        assert_eq!(extract_series_name("gpu.process.2.gpu"), "GPU Process 2");
        assert_eq!(
            extract_series_name("tpu.hloExecTiming.tensor_core_0.meanUs"),
            "tensor_core_0 meanUs"
        );
        assert_eq!(
            extract_series_name("memory_percent"),
            DEFAULT_SYSTEM_METRIC_SERIES_NAME
        );
    }
}
