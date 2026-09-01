//! Port of `core/internal/leet/systemmetrics.go`: the system-metric
//! definition table (regex pattern → display name, unit, expected range,
//! chart kind) plus the base-key / series-name extraction helpers used to
//! group per-device metrics onto shared charts.

use std::sync::LazyLock;

use regex::Regex;

use crate::units::{
    UNIT_BYTES, UNIT_CELSIUS, UNIT_GIB, UNIT_GIBPS, UNIT_MHZ, UNIT_MIB, UNIT_PERCENT, UNIT_SCALAR,
    UNIT_WATT, Unit,
};

pub const DEFAULT_SYSTEM_METRIC_SERIES_NAME: &str = "Default";

/// MetricChartKind selects the chart type used to render a system metric.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum MetricChartKind {
    /// Go zero value (`MetricChartKindLine = iota`).
    #[default]
    Line,
    FrenchFries,
}

/// MetricDef represents a system metric definition needed for displaying it on a chart.
#[derive(Debug, Clone)]
pub struct MetricDef {
    pub name: String,
    pub unit: Unit,
    /// Default min Y value
    pub min_y: f64,
    /// Default max Y value
    pub max_y: f64,
    /// Whether this is a percentage metric
    pub percentage: bool,
    /// Whether to auto-adjust Y range based on data
    pub auto_range: bool,
    pub chart_kind: MetricChartKind,
    /// Pattern to match metric names (including suffixes).
    ///
    /// PARITY: Go's `*regexp.Regexp` is nilable and chart tests construct
    /// `MetricDef` literals without it; `None` mirrors the nil pointer.
    pub regex: Option<Regex>,
}

impl MetricDef {
    /// Title returns the title to display on the metric chart.
    pub fn title(&self) -> String {
        if self.unit.name().is_empty() {
            return self.name.clone();
        }

        format!("{} ({})", self.name, self.unit.name())
    }
}

/// Row constructor for the definition table. Field order mirrors the Go
/// struct literal: name, unit, min Y, max Y, percentage, auto-range, pattern.
/// ChartKind is always the Go zero value (`Line`) in the table.
fn def(
    name: &str,
    unit: Unit,
    min_y: f64,
    max_y: f64,
    percentage: bool,
    auto_range: bool,
    pattern: &str,
) -> MetricDef {
    MetricDef {
        name: name.to_string(),
        unit,
        min_y,
        max_y,
        percentage,
        auto_range,
        chart_kind: MetricChartKind::Line,
        regex: Some(Regex::new(pattern).expect("metric regex must compile")),
    }
}

/// metricDefs holds all metric definitions.
///
/// Patterns are ordered from most specific to least specific for proper matching.
static METRIC_DEFS: LazyLock<Vec<MetricDef>> = LazyLock::new(|| {
    vec![
        // CPU metrics.
        def(
            "Process CPU",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^cpu(/l:.+)?$",
        ),
        def(
            "CPU Core",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^cpu\.\d+\.cpu_percent(/l:.+)?$",
        ),
        def(
            "Apple E-cores",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^cpu\.ecpu_percent(/l:.+)?$",
        ),
        def(
            "Apple E-cores Freq",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^cpu\.ecpu_freq(/l:.+)?$",
        ),
        def(
            "Apple P-cores",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^cpu\.pcpu_percent(/l:.+)?$",
        ),
        def(
            "Apple P-cores Freq",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^cpu\.pcpu_freq(/l:.+)?$",
        ),
        def(
            "CPU Temp",
            UNIT_CELSIUS,
            0.0,
            100.0,
            false,
            true,
            r"^cpu\.avg_temp(/l:.+)?$",
        ),
        def(
            "CPU Power",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^cpu\.powerWatts(/l:.+)?$",
        ),
        // Memory metrics.
        def(
            "System Memory",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^memory_percent(/l:.+)?$",
        ),
        def(
            "RAM Used",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^memory\.used(/l:.+)?$",
        ),
        def(
            "RAM Used",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^memory\.used_percent(/l:.+)?$",
        ),
        // Swap metrics.
        def(
            "Swap Used",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^swap\.used(/l:.+)?$",
        ),
        def(
            "Swap Used",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^swap\.used_percent(/l:.+)?$",
        ),
        // Process metrics.
        def(
            "Process Memory",
            UNIT_MIB,
            0.0,
            32768.0,
            false,
            true,
            r"^proc\.memory\.rssMB(/l:.+)?$",
        ),
        def(
            "Process Memory",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^proc\.memory\.percent(/l:.+)?$",
        ),
        def(
            "Process Memory Available",
            UNIT_MIB,
            0.0,
            32768.0,
            false,
            true,
            r"^proc\.memory\.availableMB(/l:.+)?$",
        ),
        def(
            "Process CPU Threads",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^proc\.cpu\.threads(/l:.+)?$",
        ),
        // Disk metrics - handle both aggregated and per-device
        def("Disk", UNIT_PERCENT, 0.0, 100.0, true, false, r"^disk$"),
        def(
            "Disk",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^disk\.[^.]+\.usagePercent(/l:.+)?$",
        ),
        def(
            "Disk",
            UNIT_GIB,
            0.0,
            1000.0,
            false,
            true,
            r"^disk\.[^.]+\.usageGB(/l:.+)?$",
        ),
        // Per-device I/O patterns (e.g., disk.disk4.in, disk.disk1.out) - CUMULATIVE
        def(
            "Disk I/O Total",
            UNIT_MIB,
            0.0,
            10000.0,
            false,
            true,
            r"^disk\.[^.]+\.(in|out)(/l:.+)?$",
        ),
        // Aggregated I/O patterns - CUMULATIVE
        def(
            "Disk Read Total",
            UNIT_MIB,
            0.0,
            10000.0,
            false,
            true,
            r"^disk\.in(/l:.+)?$",
        ),
        def(
            "Disk Write Total",
            UNIT_MIB,
            0.0,
            10000.0,
            false,
            true,
            r"^disk\.out(/l:.+)?$",
        ),
        // Network metrics - treat as rates instead of cumulative
        def(
            "Network Rx",
            UNIT_BYTES,
            0.0,
            100.0,
            false,
            true,
            r"^network\.recv(/l:.+)?$",
        ),
        def(
            "Network Tx",
            UNIT_BYTES,
            0.0,
            100.0,
            false,
            true,
            r"^network\.sent(/l:.+)?$",
        ),
        // System power
        def(
            "System Power",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^system\.powerWatts(/l:.+)?$",
        ),
        // Apple Neural Engine
        def(
            "Neural Engine Power",
            UNIT_WATT,
            0.0,
            50.0,
            false,
            true,
            r"^ane\.power(/l:.+)?$",
        ),
        // GPU metrics
        def(
            "GPU Utilization",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.gpu(/l:.+)?$",
        ),
        def(
            "GPU Temp",
            UNIT_CELSIUS,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.\d+\.temp(/l:.+)?$",
        ),
        def(
            "GPU Freq",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^gpu\.\d+\.freq(/l:.+)?$",
        ),
        def(
            "GPU Memory Access",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.memory(/l:.+)?$",
        ),
        def(
            "GPU Memory Allocated",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.memoryAllocated(/l:.+)?$",
        ),
        def(
            "GPU Memory Allocated",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.\d+\.memoryAllocatedBytes(/l:.+)?$",
        ),
        def(
            "GPU Memory Used",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.\d+\.memoryUsed(/l:.+)?$",
        ),
        def(
            "GPU Recovery Count",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.\d+\.recoveryCount(/l:.+)?$",
        ),
        def(
            "GPU Power Limit",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^gpu\.\d+\.enforcedPowerLimitWatts(/l:.+)?$",
        ),
        def(
            "GPU Power",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.powerPercent(/l:.+)?$",
        ),
        def(
            "GPU Power",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^gpu\.\d+\.powerWatts(/l:.+)?$",
        ),
        def(
            "GPU SM Clock",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^gpu\.\d+\.smClock(/l:.+)?$",
        ),
        def(
            "GPU Graphics Clock",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^gpu\.\d+\.graphicsClock(/l:.+)?$",
        ),
        def(
            "GPU Memory Clock",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^gpu\.\d+\.memoryClock(/l:.+)?$",
        ),
        def(
            "GPU Corrected Errors",
            UNIT_SCALAR,
            0.0,
            1000.0,
            false,
            true,
            r"^gpu\.\d+\.correctedMemoryErrors(/l:.+)?$",
        ),
        def(
            "GPU Uncorrected Errors",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.\d+\.uncorrectedMemoryErrors(/l:.+)?$",
        ),
        def(
            "GPU Encoder",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.encoderUtilization(/l:.+)?$",
        ),
        def(
            "GPU SM Active",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.smActive(/l:.+)?$",
        ),
        def(
            "GPU SM Occupancy",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.smOccupancy(/l:.+)?$",
        ),
        def(
            "GPU Tensor Pipeline",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.pipeTensorActive(/l:.+)?$",
        ),
        def(
            "GPU DRAM Active",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.dramActive(/l:.+)?$",
        ),
        def(
            "GPU FP64 Pipeline",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.pipeFp64Active(/l:.+)?$",
        ),
        def(
            "GPU FP32 Pipeline",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.pipeFp32Active(/l:.+)?$",
        ),
        def(
            "GPU FP16 Pipeline",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.pipeFp16Active(/l:.+)?$",
        ),
        def(
            "GPU Tensor HMMA",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.\d+\.pipeTensorHmmaActive(/l:.+)?$",
        ),
        def(
            "GPU PCIe Tx",
            UNIT_GIBPS,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.\d+\.pcieTxBytes(/l:.+)?$",
        ),
        def(
            "GPU PCIe Rx",
            UNIT_GIBPS,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.\d+\.pcieRxBytes(/l:.+)?$",
        ),
        def(
            "GPU NVLink Tx",
            UNIT_GIBPS,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.\d+\.nvlinkTxBytes(/l:.+)?$",
        ),
        def(
            "GPU NVLink Rx",
            UNIT_GIBPS,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.\d+\.nvlinkRxBytes(/l:.+)?$",
        ),
        // Per-process GPU metrics
        def(
            "Process GPU",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.process\.\d+\.gpu(/l:.+)?$",
        ),
        def(
            "Process GPU Temp",
            UNIT_CELSIUS,
            0.0,
            100.0,
            false,
            true,
            r"^gpu\.process\.\d+\.temp(/l:.+)?$",
        ),
        def(
            "Process GPU Memory",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.process\.\d+\.memory(/l:.+)?$",
        ),
        def(
            "Process GPU Memory",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.process\.\d+\.memoryAllocated(/l:.+)?$",
        ),
        def(
            "Process GPU Memory",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.process\.\d+\.memoryAllocatedBytes(/l:.+)?$",
        ),
        def(
            "Process GPU Memory",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^gpu\.process\.\d+\.memoryUsedBytes(/l:.+)?$",
        ),
        def(
            "Process GPU Power Limit",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^gpu\.process\.\d+\.enforcedPowerLimitWatts(/l:.+)?$",
        ),
        def(
            "Process GPU Power",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^gpu\.process\.\d+\.powerPercent(/l:.+)?$",
        ),
        def(
            "Process GPU Power",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^gpu\.process\.\d+\.powerWatts(/l:.+)?$",
        ),
        // TPU metrics — per-device gauges
        def(
            "TPU Tensorcore Utilization",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^tpu\.\d+\.tensorcoreUtilization(/l:.+)?$",
        ),
        def(
            "TPU Tensorcore Idle Duration",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^tpu\.\d+\.tensorcoreIdleDuration(/l:.+)?$",
        ),
        def(
            "TPU Duty Cycle",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^tpu\.\d+\.dutyCycle(/l:.+)?$",
        ),
        def(
            "TPU HBM Capacity Total",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^tpu\.\d+\.hbmCapacityTotal(/l:.+)?$",
        ),
        def(
            "TPU HBM Capacity Usage",
            UNIT_BYTES,
            0.0,
            32.0,
            false,
            true,
            r"^tpu\.\d+\.hbmCapacityUsage(/l:.+)?$",
        ),
        def(
            "TPU Runtime HBM Utilization",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^tpu\.\d+\.runtimeHbmUtilization(/l:.+)?$",
        ),
        def(
            "TPU HBM Memory Usage",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^tpu\.\d+\.hbmMemoryUsage(/l:.+)?$",
        ),
        // TPU metrics — latency distributions (labeled: .label.statUs)
        def(
            "TPU Buffer Transfer Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.bufferTransferLatency\..+$",
        ),
        def(
            "TPU Inbound Buffer Transfer Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.inboundBufferTransferLatency\..+$",
        ),
        def(
            "TPU Host-to-Device Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.hostToDeviceTransferLatency\..+$",
        ),
        def(
            "TPU Device-to-Host Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.deviceToHostTransferLatency\..+$",
        ),
        def(
            "TPU Collective E2E Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.collectiveE2ELatency\..+$",
        ),
        def(
            "TPU Host Compute Latency",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.hostComputeLatency\..+$",
        ),
        def(
            "TPU HLO Exec Timing",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.hloExecTiming\..+$",
        ),
        // TPU metrics — flat distributions
        def(
            "TPU gRPC TCP Min RTT",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.grpcTcpMinRtt\..+$",
        ),
        def(
            "TPU gRPC TCP Delivery Rate",
            UNIT_SCALAR,
            0.0,
            10000.0,
            false,
            true,
            r"^tpu\.grpcTcpDeliveryRate\..+$",
        ),
        // TPU metrics — HLO queue size (colon-keyed: .label)
        def(
            "TPU HLO Queue Size",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^tpu\.hloQueueSize\..+$",
        ),
        // TPU metrics — SDK-only gauges
        def(
            "TPU ICI Link Health",
            UNIT_SCALAR,
            0.0,
            1.0,
            false,
            true,
            r"^tpu\.\d+\.iciLinkHealth(/l:.+)?$",
        ),
        def(
            "TPU Throttle Score",
            UNIT_SCALAR,
            0.0,
            100.0,
            false,
            true,
            r"^tpu\.\d+\.throttleScore(/l:.+)?$",
        ),
        // IPU metrics
        def(
            "IPU Board Temp",
            UNIT_CELSIUS,
            0.0,
            100.0,
            false,
            true,
            r"^ipu\.\d+\.average board temp(/l:.+)?$",
        ),
        def(
            "IPU Die Temp",
            UNIT_CELSIUS,
            0.0,
            100.0,
            false,
            true,
            r"^ipu\.\d+\.average die temp(/l:.+)?$",
        ),
        def(
            "IPU Clock",
            UNIT_MHZ,
            0.0,
            3000.0,
            false,
            true,
            r"^ipu\.\d+\.clock(/l:.+)?$",
        ),
        def(
            "IPU Power",
            UNIT_WATT,
            0.0,
            500.0,
            false,
            true,
            r"^ipu\.\d+\.ipu power(/l:.+)?$",
        ),
        def(
            "IPU",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^ipu\.\d+\.ipu utilisation \(%\)(/l:.+)?$",
        ),
        def(
            "IPU Session",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^ipu\.\d+\.ipu utilisation \(session\)(/l:.+)?$",
        ),
        // Trainium metrics
        def(
            "Neuron Core",
            UNIT_PERCENT,
            0.0,
            100.0,
            true,
            false,
            r"^trn\.\d+\.neuroncore_utilization(/l:.+)?$",
        ),
        def(
            "Trainium Host Memory",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.host_total_memory_usage(/l:.+)?$",
        ),
        def(
            "Neuron Device Memory",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.neuron_device_total_memory_usage(/l:.+)?$",
        ),
        def(
            "Trainium Host App Memory",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.host_memory_usage\.application_memory(/l:.+)?$",
        ),
        def(
            "Trainium Host Constants",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.host_memory_usage\.constants(/l:.+)?$",
        ),
        def(
            "Trainium Host DMA",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.host_memory_usage\.dma_buffers(/l:.+)?$",
        ),
        def(
            "Trainium Host Tensors",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.host_memory_usage\.tensors(/l:.+)?$",
        ),
        def(
            "Neuron Constants",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.\d+\.neuroncore_memory_usage\.constants(/l:.+)?$",
        ),
        def(
            "Neuron Model Code",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.\d+\.neuroncore_memory_usage\.model_code(/l:.+)?$",
        ),
        def(
            "Neuron Scratchpad",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.\d+\.neuroncore_memory_usage\.model_shared_scratchpad(/l:.+)?$",
        ),
        def(
            "Neuron Runtime",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.\d+\.neuroncore_memory_usage\.runtime_memory(/l:.+)?$",
        ),
        def(
            "Neuron Tensors",
            UNIT_GIB,
            0.0,
            32.0,
            false,
            true,
            r"^trn\.\d+\.neuroncore_memory_usage\.tensors(/l:.+)?$",
        ),
    ]
});

/// MatchMetricDef finds the matching definition for a given metric name
pub fn match_metric_def(metric_name: &str) -> Option<&'static MetricDef> {
    // Remove any prefix slashes if present
    let metric_name = metric_name.strip_prefix('/').unwrap_or(metric_name);

    // Try each pattern in order (most specific first)
    METRIC_DEFS.iter().find(|d| {
        // The table always sets `regex`; `None` cannot match (Go would nil-panic).
        d.regex.as_ref().is_some_and(|re| re.is_match(metric_name))
    })
}

/// ExtractBaseKey extracts the base metric name for grouping.
///
/// For example, "gpu.0.temp" -> "gpu.temp", "cpu.0.cpu_percent" -> "cpu.cpu_percent"
/// "disk.disk4.in" -> "disk.in_out" (special case for disk I/O)
/// Also handles suffixes like "/l:..." for shared mode.
pub fn extract_base_key(metric_name: &str) -> String {
    // Remove suffix if present
    let mut metric_name = metric_name;
    // PARITY: Go checks idx > 0, so a name *starting* with "/l:" keeps its suffix.
    if let Some(idx) = metric_name.find("/l:")
        && idx > 0
    {
        metric_name = &metric_name[..idx];
    }

    let parts: Vec<&str> = metric_name.split('.').collect();

    // Special handling for disk I/O metrics: disk.{device}.in/out -> disk.io_per_device
    if parts.len() == 3 && parts[0] == "disk" && (parts[2] == "in" || parts[2] == "out") {
        return "disk.io_per_device".to_string();
    }

    // Handle patterns like "gpu.0.temp" -> "gpu.temp"
    if parts.len() >= 3 && is_numeric(parts[1]) {
        return format!("{}.{}", parts[0], parts[2..].join("."));
    }

    // Handle patterns like "gpu.process.0.temp" -> "gpu.process.temp"
    if parts.len() >= 4 && parts[1] == "process" && is_numeric(parts[2]) {
        return format!("{}.{}.{}", parts[0], parts[1], parts[3..].join("."));
    }

    // Handle TPU non-per-device patterns like
    // "tpu.hloExecTiming.tensor_core_0.meanUs" -> "tpu.hloExecTiming"
    // "tpu.hloQueueSize.tensor_core_0" -> "tpu.hloQueueSize"
    if parts.len() >= 3 && parts[0] == "tpu" && !is_numeric(parts[1]) {
        return format!("{}.{}", parts[0], parts[1]);
    }

    metric_name.to_string()
}

/// ExtractSeriesName extracts the series identifier from a metric name
/// e.g., "gpu.0.temp" -> "GPU 0", "disk.disk4.in" -> "disk4 in"
pub fn extract_series_name(metric_name: &str) -> String {
    // Remove suffix if present
    let mut metric_name = metric_name;
    // PARITY: Go checks idx > 0, so a name *starting* with "/l:" keeps its suffix.
    if let Some(idx) = metric_name.find("/l:")
        && idx > 0
    {
        metric_name = &metric_name[..idx];
    }

    let parts: Vec<&str> = metric_name.split('.').collect();

    // Handle disk I/O patterns like "disk.disk4.in", "disk.nvme0n1.out"
    if parts.len() == 3 && parts[0] == "disk" && (parts[2] == "in" || parts[2] == "out") {
        let disk_name = parts[1];
        let direction = parts[2];
        if direction == "in" {
            return format!("{disk_name} read");
        }
        return format!("{disk_name} write");
    }

    // Handle patterns like "gpu.0.temp"
    if parts.len() >= 3 && is_numeric(parts[1]) {
        let prefix = parts[0].to_uppercase();
        let index = parts[1];
        return format!("{prefix} {index}");
    }

    // Handle patterns like "gpu.process.0.temp"
    if parts.len() >= 4 && parts[1] == "process" && is_numeric(parts[2]) {
        let prefix = parts[0].to_uppercase();
        let index = parts[2];
        return format!("{prefix} Process {index}");
    }

    // Handle patterns like "cpu.0.cpu_percent"
    // PARITY: unreachable — the generic indexed branch above already matched
    // ("cpu.2.cpu_percent" yields "CPU 2", as Go's own test expects).
    if parts.len() >= 3 && parts[0] == "cpu" && is_numeric(parts[1]) {
        return format!("Core {}", parts[1]);
    }

    // Handle TPU non-per-device patterns like
    // "tpu.hloExecTiming.tensor_core_0.meanUs" -> "tensor_core_0 meanUs"
    // "tpu.hloQueueSize.tensor_core_0" -> "tensor_core_0"
    if parts.len() >= 3 && parts[0] == "tpu" && !is_numeric(parts[1]) {
        return parts[2..].join(" ");
    }

    // For non-indexed metrics, return a default series name
    DEFAULT_SYSTEM_METRIC_SERIES_NAME.to_string()
}

/// isNumeric checks if a string is a number.
///
/// PARITY: Go uses `strconv.Atoi` — base-10 with optional sign, 64-bit range;
/// `parse::<i64>` matches those semantics.
fn is_numeric(s: &str) -> bool {
    s.parse::<i64>().is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::units::{UNIT_GIB, UNIT_MIB, UNIT_MIBPS};

    /// Rust-only: forces the LazyLock table to build, proving every pattern
    /// compiles under the `regex` crate, and pins the row count to Go's.
    #[test]
    fn metric_defs_all_regexes_compile_and_row_count_matches_go() {
        assert_eq!(METRIC_DEFS.len(), 102);
        for d in METRIC_DEFS.iter() {
            assert!(d.regex.is_some(), "table row {:?} missing regex", d.name);
        }
    }

    #[test]
    fn match_metric_def_basic_families() {
        struct Case {
            name: &'static str,
            metric: &'static str,
            want_name: &'static str,
            want_unit: &'static str,
        }
        let cases = [
            Case {
                name: "CPU core %",
                metric: "cpu.0.cpu_percent",
                want_name: "CPU Core",
                want_unit: "%",
            },
            Case {
                name: "GPU temp",
                metric: "gpu.1.temp",
                want_name: "GPU Temp",
                want_unit: "°C",
            },
            Case {
                name: "Disk per-device I/O",
                metric: "disk.disk4.in",
                want_name: "Disk I/O Total",
                want_unit: "B",
            },
            Case {
                name: "Disk write total",
                metric: "disk.out",
                want_name: "Disk Write Total",
                want_unit: "B",
            },
            Case {
                name: "RAM used MB",
                metric: "memory.used",
                want_name: "RAM Used",
                want_unit: "B",
            },
            Case {
                name: "System memory %",
                metric: "memory_percent",
                want_name: "System Memory",
                want_unit: "%",
            },
            Case {
                name: "Network rx bytes",
                metric: "network.recv",
                want_name: "Network Rx",
                want_unit: "B",
            },
            Case {
                name: "Process GPU mem bytes",
                metric: "gpu.process.3.memoryAllocatedBytes",
                want_name: "Process GPU Memory",
                want_unit: "B",
            },
            Case {
                name: "TPU runtime HBM util",
                metric: "tpu.0.runtimeHbmUtilization",
                want_name: "TPU Runtime HBM Utilization",
                want_unit: "%",
            },
            Case {
                name: "TPU tensorcore idle duration",
                metric: "tpu.1.tensorcoreIdleDuration",
                want_name: "TPU Tensorcore Idle Duration",
                want_unit: "",
            },
        ];
        for tc in cases {
            let def = match_metric_def(tc.metric)
                .unwrap_or_else(|| panic!("{}: no def matched metric {}", tc.name, tc.metric));
            let want_title = if tc.want_unit.is_empty() {
                tc.want_name.to_string()
            } else {
                format!("{} ({})", tc.want_name, tc.want_unit)
            };
            assert_eq!(def.title(), want_title, "metric: {}", tc.metric);
        }
    }

    #[test]
    fn extract_base_key() {
        let cases = [
            ("gpu.0.temp", "gpu.temp"),
            ("gpu.0.temp/l:0:GPU0", "gpu.temp"),
            ("gpu.process.2.temp", "gpu.process.temp"),
            ("disk.disk4.out", "disk.io_per_device"),
            ("cpu.0.cpu_percent", "cpu.cpu_percent"),
            ("memory.used", "memory.used"),
        ];
        for (input, want) in cases {
            let got = super::extract_base_key(input);
            assert_eq!(got, want, "input: {input}");
        }
    }

    #[test]
    fn extract_series_name() {
        let cases = [
            ("gpu.3.temp", "GPU 3"),
            ("gpu.process.2.temp", "GPU Process 2"),
            ("cpu.2.cpu_percent", "CPU 2"),
            ("disk.disk4.in", "disk4 read"),
            ("disk.disk4.out", "disk4 write"),
            ("memory.used", "Default"),
        ];
        for (input, want) in cases {
            let got = super::extract_series_name(input);
            assert_eq!(got, want, "input: {input}");
        }
    }

    #[test]
    #[allow(clippy::approx_constant)] // Go test data includes 3.14.
    fn unit_format() {
        let cases: [(f64, Unit, &str); 20] = [
            (0.0, UNIT_PERCENT, "0"),
            (9.99, UNIT_PERCENT, "9.99%"),
            (100.0, UNIT_PERCENT, "100%"),
            (950.0, UNIT_MHZ, "950MHz"),
            (2500.0, UNIT_MHZ, "2.5GHz"),
            (1024.0, UNIT_BYTES, "1KiB"),
            (1536.0, UNIT_BYTES, "1.5KiB"),
            (512.0, UNIT_MIB, "512MiB"),
            (1536.0, UNIT_MIB, "1.5GiB"),
            (1048576.0, UNIT_MIB, "1TiB"),
            (256.0, UNIT_GIB, "256GiB"),
            (1536.0, UNIT_GIB, "1.5TiB"),
            (2048.0, UNIT_MIBPS, "2.15GB/s"),
            (0.005, UNIT_SCALAR, "0.005"),
            (0.5, UNIT_SCALAR, "0.5"),
            (3.14, UNIT_SCALAR, "3.14"),
            (-3.14, UNIT_SCALAR, "-3.14"),
            (0.0000031415, UNIT_SCALAR, "3.14e-06"),
            (1200.0, UNIT_SCALAR, "1.2e+03"),
            (1200000.0, UNIT_SCALAR, "1.2e+06"),
        ];
        for (val, unit, want) in cases {
            let got = unit.format(val);
            assert_eq!(got, want, "val: {val}, unit: {unit:?}");
        }
    }
}
