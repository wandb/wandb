use log::debug;
use std::{
    collections::HashMap,
    io::{Error, ErrorKind},
    process::Command,
};

use serde::Serialize;
use serde_json::Value;
use which::which;

use crate::{
    metrics::MetricValue,
    wandb_internal::{GpuAmdInfo, MetadataRequest},
};

// AMD GPU stats are collecting using the rocm-smi tool.
// TODO: Port the relevant parts of
// https://github.com/ROCm/rocm_smi_lib/blob/amd-staging/include/rocm_smi/rocm_smi.h
// https://github.com/ROCm/rocm_smi_lib/blob/amd-staging/python_smi_tools/rsmiBindings.py
// to Rust and use it to get GPU stats directly.

const ROCM_SMI_DEFAULT_PATH: &str = "/usr/bin/rocm-smi";

/// Struct to hold AMD GPU stats and metadata.
#[derive(Debug, Default, Clone, Serialize)]
pub struct GpuStats {
    // dynamic data
    gpu_utilization: f64,
    memory_allocated: f64,
    memory_read_write_activity: f64,
    memory_overdrive: f64,
    temperature: f64,
    power_watts: f64,
    power_percent: f64,
    // static data
    id: String,
    unique_id: Option<String>,
    vbios_version: Option<String>,
    performance_level: Option<String>,
    gpu_overdrive: Option<String>,
    gpu_memory_overdrive: Option<String>,
    max_power: Option<String>,
    series: Option<String>,
    model: Option<String>,
    vendor: Option<String>,
    sku: Option<String>,
    sclk_range: Option<String>,
    mclk_range: Option<String>,
}

impl GpuStats {
    /// Convert the stats into a Vec of (metric_name, metric_value) tuples.
    ///
    /// The keys are formatted as `gpu.<gpu_index>.<metric_name>`, which
    /// is the format expected by the Weights & Biases UI.
    pub fn to_vec(&self, index: String) -> Vec<(String, MetricValue)> {
        vec![
            (
                format!("gpu.{}.gpu", index),
                MetricValue::Float(self.gpu_utilization),
            ),
            (
                format!("gpu.{}.memoryAllocated", index),
                MetricValue::Float(self.memory_allocated),
            ),
            (
                format!("gpu.{}.memoryReadWriteActivity", index),
                MetricValue::Float(self.memory_read_write_activity),
            ),
            (
                format!("gpu.{}.memoryOverDrive", index),
                MetricValue::Float(self.memory_overdrive),
            ),
            (
                format!("gpu.{}.temp", index),
                MetricValue::Float(self.temperature),
            ),
            (
                format!("gpu.{}.powerWatts", index),
                MetricValue::Float(self.power_watts),
            ),
            (
                format!("gpu.{}.powerPercent", index),
                MetricValue::Float(self.power_percent),
            ),
        ]
    }
}

impl From<&serde_json::Map<String, Value>> for GpuStats {
    /// Convert the JSON stats returned by rocm-smi into GpuStats.
    fn from(stats: &serde_json::Map<String, Value>) -> Self {
        let mut gpu_stats = GpuStats::default();

        // GPU Utilization
        if let Some(v) = stats.get("GPU use (%)").and_then(|v| v.as_str()) {
            gpu_stats.gpu_utilization = parse_value(v);
        }

        // Memory (try multiple possible keys)
        if let Some(v) = stats.get("GPU memory use (%)").and_then(|v| v.as_str()) {
            gpu_stats.memory_allocated = parse_value(v);
        } else if let Some(v) = stats
            .get("GPU Memory Allocated (VRAM%)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.memory_allocated = parse_value(v);
        }

        // Memory Read/Write Activity
        if let Some(v) = stats
            .get("GPU Memory Read/Write Activity (%)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.memory_read_write_activity = parse_value(v);
        }

        // Memory Overdrive
        if let Some(v) = stats
            .get("GPU Memory OverDrive value (%)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.memory_overdrive = parse_value(v);
        }

        // Temperature
        if let Some(v) = stats
            .get("Temperature (Sensor memory) (C)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.temperature = parse_value(v);
        }

        // Power (try both older and MI300X formats)
        let power_watts = stats
            .get("Average Graphics Package Power (W)")
            // For MI300X GPUs, instead of "Average Graphics Package Power (W)",
            // "Current Socket Graphics Package Power (W)" is reported.
            .or_else(|| stats.get("Current Socket Graphics Package Power (W)"))
            .and_then(|v| v.as_str())
            .map(parse_value);

        let max_power = stats
            .get("Max Graphics Package Power (W)")
            .and_then(|v| v.as_str())
            .map(parse_value);

        if let (Some(current), Some(max)) = (power_watts, max_power) {
            gpu_stats.power_watts = current;
            if max > 0.0 {
                gpu_stats.power_percent = (current / max) * 100.0;
            }
        }

        // Static data
        if let Some(v) = stats
            .get("GPU ID")
            .or_else(|| stats.get("Device ID"))
            .and_then(|v| v.as_str())
        {
            gpu_stats.id = v.to_string();
        }

        if let Some(v) = stats.get("Unique ID").and_then(|v| v.as_str()) {
            gpu_stats.unique_id = Some(v.to_string());
        }

        if let Some(v) = stats.get("VBIOS version").and_then(|v| v.as_str()) {
            gpu_stats.vbios_version = Some(v.to_string());
        }

        if let Some(v) = stats.get("Performance Level").and_then(|v| v.as_str()) {
            gpu_stats.performance_level = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("GPU OverDrive value (%)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.gpu_overdrive = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("GPU Memory OverDrive value (%)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.gpu_memory_overdrive = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("Max Graphics Package Power (W)")
            .and_then(|v| v.as_str())
        {
            gpu_stats.max_power = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("Card Series")
            .or_else(|| stats.get("Card series"))
            .and_then(|v| v.as_str())
        {
            gpu_stats.series = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("Card Model")
            .or_else(|| stats.get("Card model"))
            .and_then(|v| v.as_str())
        {
            gpu_stats.model = Some(v.to_string());
        }

        if let Some(v) = stats
            .get("Card Vendor")
            .or_else(|| stats.get("Card vendor"))
            .and_then(|v| v.as_str())
        {
            gpu_stats.vendor = Some(v.to_string());
        }

        if let Some(v) = stats.get("Card SKU").and_then(|v| v.as_str()) {
            gpu_stats.sku = Some(v.to_string());
        }

        if let Some(v) = stats.get("Valid sclk range").and_then(|v| v.as_str()) {
            gpu_stats.sclk_range = Some(v.to_string());
        }

        if let Some(v) = stats.get("Valid mclk range").and_then(|v| v.as_str()) {
            gpu_stats.mclk_range = Some(v.to_string());
        }

        gpu_stats
    }
}

/// Parse a value from a string, removing the trailing '%' if present.
fn parse_value(s: &str) -> f64 {
    s.trim_end_matches('%').parse().unwrap_or_default()
}

/// Struct to collect AMD GPU stats and metadata using rocm-smi.
pub struct GpuAmd {
    pub rocm_smi_path: String,
}

impl GpuAmd {
    pub fn new() -> Option<Self> {
        is_driver_installed() // Check if AMD GPU driver is installed
            .then(|| find_rocm_smi().ok()) // Find rocm-smi binary
            .flatten()
            .and_then(|path| {
                let gpu = Self {
                    rocm_smi_path: path,
                };
                // Check if we can read stats using the found rocm-smi
                (!gpu.get_rocm_smi_stats().unwrap_or_default().is_empty()).then_some(gpu)
            })
    }

    /// Get GPU metrics using rocm-smi.
    pub fn get_metrics(&self) -> Result<Vec<(String, MetricValue)>, std::io::Error> {
        let raw_stats = self.get_rocm_smi_stats()?;

        let metrics: Vec<(String, MetricValue)> = raw_stats
            .iter()
            .flat_map(|(k, v)| v.to_vec(k.clone()))
            .collect();

        Ok(metrics)
    }

    /// Get GPU metadata using rocm-smi.
    pub fn get_metadata(&self) -> Result<MetadataRequest, std::io::Error> {
        let raw_stats = self.get_rocm_smi_stats()?;

        let gpu_amd: Vec<GpuAmdInfo> = raw_stats
            .iter()
            .map(|(k, v)| {
                let mut info = GpuAmdInfo {
                    id: k.clone(),
                    ..Default::default()
                };
                if let Some(unique_id) = &v.unique_id {
                    info.unique_id = unique_id.clone();
                }
                if let Some(vbios_version) = &v.vbios_version {
                    info.vbios_version = vbios_version.clone();
                }
                if let Some(performance_level) = &v.performance_level {
                    info.performance_level = performance_level.clone();
                }
                if let Some(gpu_overdrive) = &v.gpu_overdrive {
                    info.gpu_overdrive = gpu_overdrive.clone();
                }
                if let Some(gpu_memory_overdrive) = &v.gpu_memory_overdrive {
                    info.gpu_memory_overdrive = gpu_memory_overdrive.clone();
                }
                if let Some(max_power) = &v.max_power {
                    info.max_power = max_power.clone();
                }
                if let Some(series) = &v.series {
                    info.series = series.clone();
                }
                if let Some(model) = &v.model {
                    info.model = model.clone();
                }
                if let Some(vendor) = &v.vendor {
                    info.vendor = vendor.clone();
                }
                if let Some(sku) = &v.sku {
                    info.sku = sku.clone();
                }
                if let Some(sclk_range) = &v.sclk_range {
                    info.sclk_range = sclk_range.clone();
                }
                if let Some(mclk_range) = &v.mclk_range {
                    info.mclk_range = mclk_range.clone();
                }

                info
            })
            .collect();

        Ok(MetadataRequest {
            gpu_count: raw_stats.len() as u32,
            gpu_type: gpu_amd[0].series.clone(),
            gpu_amd: gpu_amd,
            ..Default::default()
        })
    }

    /// Call rocm-smi to get GPU stats.
    fn get_rocm_smi_stats(&self) -> Result<HashMap<String, GpuStats>, std::io::Error> {
        let output = Command::new(&self.rocm_smi_path)
            .args(["-a", "--json"])
            .output()?;

        if !output.status.success() {
            return Err(Error::new(ErrorKind::Other, "rocm-smi command failed"));
        }

        let raw: HashMap<String, Value> =
            serde_json::from_slice(&output.stdout).unwrap_or_default();
        Ok(raw
            .iter()
            .filter(|(key, _)| key.starts_with("card"))
            .filter_map(|(key, value)| {
                value.as_object().map(|stats| {
                    (
                        // Remove the "card" prefix from the key
                        key.clone().strip_prefix("card").unwrap_or(key).to_string(),
                        // Convert the stats into GpuStats
                        stats.into(),
                    )
                })
            })
            .collect())
    }
}

/// Find the rocm-smi binary.
fn find_rocm_smi() -> Result<String, String> {
    // Try to find rocm_smi in PATH
    if let Ok(rocm_path) = which("rocm-smi") {
        debug!("Found rocm-smi at {}", rocm_path.display());
        if let Some(p) = rocm_path.to_str() {
            return Ok(p.to_string());
        }
    }

    // Fall back to default path
    if let Ok(path) = which(ROCM_SMI_DEFAULT_PATH) {
        debug!("Found rocm-smi at {}", path.display());
        return Ok(ROCM_SMI_DEFAULT_PATH.to_string());
    }

    Err("rocm_smi not found".to_string())
}

/// Check if the AMD GPU driver is installed and loaded.
fn is_driver_installed() -> bool {
    // Inspired by rocm_smi_lib, see
    // https://github.com/ROCm/rocm_smi_lib/blob/6f51cd651e4116b04c2df6a2afe8859558bdba66/python_smi_tools/rocm_smi.py#L89
    std::fs::read_to_string("/sys/module/amdgpu/initstate")
        .map(|content| content.contains("live"))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashMap;

    impl GpuAmd {
        #[cfg(test)]
        fn get_metrics_with_stats(
            &self,
            stats: HashMap<String, GpuStats>,
        ) -> Result<Vec<(String, MetricValue)>, std::io::Error> {
            let metrics: Vec<(String, MetricValue)> = stats
                .iter()
                .flat_map(|(k, v)| v.to_vec(k.clone()))
                .collect();

            Ok(metrics)
        }

        #[cfg(test)]
        fn get_metadata_with_stats(
            &self,
            stats: HashMap<String, GpuStats>,
        ) -> Result<MetadataRequest, std::io::Error> {
            let gpu_amd: Vec<GpuAmdInfo> = stats
                .iter()
                .map(|(k, _)| {
                    let info = GpuAmdInfo {
                        id: k.clone(),
                        ..Default::default()
                    };
                    info
                })
                .collect();

            Ok(MetadataRequest {
                gpu_count: stats.len() as u32,
                gpu_amd,
                ..Default::default()
            })
        }
    }

    /// Mock GPU stats for two AMD GPUs using ROCM 5 format.
    fn get_rocm_smi_stats_rocm5_mock() -> HashMap<String, GpuStats> {
        let json_str = r#"{
            "card0": {
                "GPU ID": "0x740c",
                "Unique ID": "0x719d230578348e8c",
                "VBIOS version": "113-D65209-073",
                "Temperature (Sensor memory) (C)": "43.0",
                "GPU use (%)": "10",
                "GPU memory use (%)": "20",
                "Average Graphics Package Power (W)": "89.0",
                "Max Graphics Package Power (W)": "560.0",
                "Performance Level": "auto",
                "GPU OverDrive value (%)": "0",
                "GPU Memory OverDrive value (%)": "0",
                "Card series": "AMD INSTINCT MI250 (MCM) OAM AC MBA",
                "Card model": "0x0b0c",
                "Card vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
                "Card SKU": "D65209",
                "Valid sclk range": "500Mhz - 1700Mhz",
                "Valid mclk range": "400Mhz - 1600Mhz"
            },
            "card1": {
                "GPU ID": "0x740c",
                "Unique ID": "0x719d230578348e8c",
                "VBIOS version": "113-D65209-073",
                "Temperature (Sensor memory) (C)": "43.0",
                "GPU use (%)": "20",
                "GPU memory use (%)": "0",
                "Average Graphics Package Power (W)": "89.0",
                "Max Graphics Package Power (W)": "560.0",
                "Performance Level": "auto",
                "Card series": "AMD INSTINCT MI250 (MCM) OAM AC MBA"
            },
            "system": {
                "Driver version": "6.2.4"
            }
        }"#;

        let raw: HashMap<String, serde_json::Value> = serde_json::from_str(json_str).unwrap();
        raw.iter()
            .filter(|(key, _)| key.starts_with("card"))
            .filter_map(|(key, value)| {
                value.as_object().map(|stats| {
                    (
                        key.strip_prefix("card").unwrap_or(key).to_string(),
                        stats.into(),
                    )
                })
            })
            .collect()
    }

    /// Mock GPU stats for one AMD GPU using ROCM 6 format.
    fn get_rocm_smi_stats_rocm6_mock() -> HashMap<String, GpuStats> {
        let json_str = r#"{
            "card0": {
                "Device ID": "0x740c",
                "Unique ID": "0x1f9de0957d137942",
                "VBIOS version": "113-D65209-073",
                "Temperature (Sensor memory) (C)": "53.0",
                "GPU use (%)": "0",
                "GPU Memory Allocated (VRAM%)": "0",
                "GPU Memory Read/Write Activity (%)": "0",
                "Average Graphics Package Power (W)": "91.0",
                "Max Graphics Package Power (W)": "560.0",
                "Performance Level": "auto",
                "GPU OverDrive value (%)": "0",
                "GPU Memory OverDrive value (%)": "0",
                "Card Series": "AMD INSTINCT MI250 (MCM) OAM AC MBA",
                "Card Model": "0x740c",
                "Card Vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
                "Card SKU": "D65209",
                "Valid sclk range": "500Mhz - 1700Mhz",
                "Valid mclk range": "400Mhz - 1600Mhz"
            },
            "system": {
                "Driver version": "6.2.4"
            }
        }"#;

        let raw: HashMap<String, serde_json::Value> = serde_json::from_str(json_str).unwrap();
        raw.iter()
            .filter(|(key, _)| key.starts_with("card"))
            .filter_map(|(key, value)| {
                value.as_object().map(|stats| {
                    (
                        key.strip_prefix("card").unwrap_or(key).to_string(),
                        stats.into(),
                    )
                })
            })
            .collect()
    }

    #[test]
    /// Test that the AMD GPU stats in ROCM 5 format are parsed correctly.
    fn test_parse_stats_rocm5() {
        let stats = serde_json::Map::from_iter(vec![
            ("GPU use (%)".to_string(), json!("10")),
            ("GPU memory use (%)".to_string(), json!("20")),
            ("Temperature (Sensor memory) (C)".to_string(), json!("43.0")),
            (
                "Average Graphics Package Power (W)".to_string(),
                json!("89.0"),
            ),
            ("Max Graphics Package Power (W)".to_string(), json!("560.0")),
        ]);

        let gpu_stats: GpuStats = (&stats).into();

        assert_eq!(gpu_stats.gpu_utilization, 10.0);
        assert_eq!(gpu_stats.memory_allocated, 20.0);
        assert_eq!(gpu_stats.temperature, 43.0);
        assert_eq!(gpu_stats.power_watts, 89.0);
        assert_eq!(gpu_stats.power_percent, (89.0 / 560.0) * 100.0);
    }

    #[test]
    /// Test that the AMD GPU stats in ROCM 6 format are parsed correctly.
    fn test_parse_stats_rocm6() {
        let stats = serde_json::Map::from_iter(vec![
            ("GPU use (%)".to_string(), json!("10")),
            ("GPU Memory Allocated (VRAM%)".to_string(), json!("20")),
            ("Temperature (Sensor memory) (C)".to_string(), json!("43.0")),
            (
                "Average Graphics Package Power (W)".to_string(),
                json!("89.0"),
            ),
            ("Max Graphics Package Power (W)".to_string(), json!("560.0")),
        ]);

        let gpu_stats: GpuStats = (&stats).into();

        assert_eq!(gpu_stats.gpu_utilization, 10.0);
        assert_eq!(gpu_stats.memory_allocated, 20.0);
        assert_eq!(gpu_stats.temperature, 43.0);
        assert_eq!(gpu_stats.power_watts, 89.0);
        assert_eq!(gpu_stats.power_percent, (89.0 / 560.0) * 100.0);
    }

    #[test]
    /// Test that the AMD GPU stats in ROCM 6 format are parsed correctly for MI300X GPUs.
    fn test_parse_stats_rocm6_mi300x() {
        let stats = serde_json::Map::from_iter(vec![
            ("GPU use (%)".to_string(), json!("10")),
            ("GPU Memory Allocated (VRAM%)".to_string(), json!("20")),
            ("Temperature (Sensor memory) (C)".to_string(), json!("43.0")),
            (
                "Current Socket Graphics Package Power (W)".to_string(),
                json!("89.0"),
            ),
            ("Max Graphics Package Power (W)".to_string(), json!("560.0")),
        ]);

        let gpu_stats: GpuStats = (&stats).into();

        assert_eq!(gpu_stats.gpu_utilization, 10.0);
        assert_eq!(gpu_stats.memory_allocated, 20.0);
        assert_eq!(gpu_stats.temperature, 43.0);
        assert_eq!(gpu_stats.power_watts, 89.0);
        assert_eq!(gpu_stats.power_percent, (89.0 / 560.0) * 100.0);
    }

    #[test]
    /// Test that the AMD GPU stats are converted to metrics correctly.
    fn test_get_metrics() {
        let gpu = GpuAmd {
            rocm_smi_path: "mock_path".to_string(),
        };

        // Test with ROCM 5 mock data
        {
            let metrics = gpu
                .get_metrics_with_stats(get_rocm_smi_stats_rocm5_mock())
                .unwrap();
            assert_eq!(metrics.len(), 14); // 7 metrics * 2 cards
        }

        // Test with ROCM 6 mock data
        {
            let metrics = gpu
                .get_metrics_with_stats(get_rocm_smi_stats_rocm6_mock())
                .unwrap();
            assert_eq!(metrics.len(), 7); // 7 metrics * 1 card
        }
    }

    #[test]
    /// Test that the AMD GPU stats are converted to metadata correctly.
    fn test_get_metadata() {
        let gpu = GpuAmd {
            rocm_smi_path: "mock_path".to_string(),
        };

        // Test with ROCM 5 mock data
        {
            let metadata = gpu
                .get_metadata_with_stats(get_rocm_smi_stats_rocm5_mock())
                .unwrap();
            assert_eq!(metadata.gpu_count, 2);
            assert_eq!(metadata.gpu_amd.len(), 2);
        }

        // Test with ROCM 6 mock data
        {
            let metadata = gpu
                .get_metadata_with_stats(get_rocm_smi_stats_rocm6_mock())
                .unwrap();
            assert_eq!(metadata.gpu_count, 1);
            assert_eq!(metadata.gpu_amd.len(), 1);
        }
    }
}
