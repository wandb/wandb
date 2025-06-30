use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;
use tonic::transport::{Channel, ClientTlsConfig};
use tonic::Request;

mod tpuproto {
    tonic::include_proto!("tpuproto");
}

use tpuproto::{runtime_metric_service_client::RuntimeMetricServiceClient, MetricRequest};

const GOOGLE_TPU_VENDOR_ID: &str = "0x1ae0";
const GRPC_ADDR: &str = "http://localhost:8431";

#[derive(Debug, Clone)]
struct TPUChip {
    name: String,
    hbm_gib: u32,
    devices_per_chip: u32,
}

#[derive(Debug)]
struct TPU {
    name: String,
    client: Option<RuntimeMetricServiceClient<Channel>>,
    chip: TPUChip,
    count: usize,
}

impl TPU {
    async fn new() -> Option<Self> {
        let (chip, count) = Self::get_local_tpu_chips();
        if count == 0 {
            return None;
        }

        let channel = Channel::from_static(GRPC_ADDR).connect().await.ok()?;
        let client = RuntimeMetricServiceClient::new(channel);

        Some(TPU {
            name: "tpu".to_string(),
            client: Some(client),
            chip,
            count,
        })
    }

    async fn sample(&mut self) -> Result<HashMap<String, f64>, Box<dyn std::error::Error>> {
        let client = self
            .client
            .as_mut()
            .ok_or("TPU client is not initialized")?;

        let total_memory = self
            .get_metrics(client, "tpu.runtime.hbm.memory.total.bytes")
            .await?;
        let memory_usage = self
            .get_metrics(client, "tpu.runtime.hbm.memory.usage.bytes")
            .await?;
        let duty_cycle = self
            .get_metrics(client, "tpu.runtime.tensorcore.dutycycle.percent")
            .await?;

        let mut metrics = HashMap::new();
        for (&device_id, &usage) in &memory_usage {
            let total = total_memory.get(&device_id).copied().unwrap_or(1.0);
            metrics.insert(
                format!("{}.{}.memoryUsage", self.name, device_id),
                usage / total * 100.0,
            );
            metrics.insert(
                format!("{}.{}.memoryUsageBytes", self.name, device_id),
                usage,
            );
        }
        for (&device_id, &duty) in &duty_cycle {
            metrics.insert(format!("{}.{}.dutyCycle", self.name, device_id), duty);
        }

        Ok(metrics)
    }

    async fn get_metrics(
        &self,
        client: &mut RuntimeMetricServiceClient<Channel>,
        metric_name: &str,
    ) -> Result<HashMap<i64, f64>, Box<dyn std::error::Error>> {
        let request = Request::new(MetricRequest {
            metric_name: metric_name.to_string(),
        });
        let response = client.get_runtime_metric(request).await?.into_inner();

        let mut metrics = HashMap::new();
        for metric in response.metric.unwrap().metrics {
            let device_id = metric.attribute.unwrap().value.unwrap().int_attr;
            let value = metric.gauge.unwrap().as_double.unwrap();
            metrics.insert(device_id, value);
        }
        Ok(metrics)
    }

    fn get_local_tpu_chips() -> (TPUChip, usize) {
        let pci_devices = fs::read_dir("/sys/bus/pci/devices").ok()?;
        let mut counter = HashMap::new();

        for entry in pci_devices.flatten() {
            let path = entry.path();
            let vendor_id = fs::read_to_string(path.join("vendor"))
                .ok()?
                .trim()
                .to_string();
            if vendor_id != GOOGLE_TPU_VENDOR_ID {
                continue;
            }
            let device_id = fs::read_to_string(path.join("device"))
                .ok()?
                .trim()
                .to_string();
            let subsystem_id = fs::read_to_string(path.join("subsystem_device"))
                .ok()?
                .trim()
                .to_string();

            if let Ok(chip) = Self::tpu_chip_from_pci_device_id(&device_id, &subsystem_id) {
                *counter.entry(chip).or_insert(0) += 1;
            }
        }

        counter
            .into_iter()
            .max_by_key(|&(_, count)| count)
            .unwrap_or_default()
    }

    fn tpu_chip_from_pci_device_id(
        device_id: &str,
        subsystem_id: &str,
    ) -> Result<TPUChip, &'static str> {
        match (device_id, subsystem_id) {
            ("0x0027", "0x004e") => Ok(TPUChip {
                name: "v2".to_string(),
                hbm_gib: 8,
                devices_per_chip: 2,
            }),
            ("0x0027", "0x004f") => Ok(TPUChip {
                name: "v3".to_string(),
                hbm_gib: 16,
                devices_per_chip: 2,
            }),
            ("0x005e", _) => Ok(TPUChip {
                name: "v4".to_string(),
                hbm_gib: 32,
                devices_per_chip: 1,
            }),
            ("0x0063", _) => Ok(TPUChip {
                name: "v5e".to_string(),
                hbm_gib: 16,
                devices_per_chip: 1,
            }),
            ("0x0062", _) => Ok(TPUChip {
                name: "v5p".to_string(),
                hbm_gib: 95,
                devices_per_chip: 1,
            }),
            ("0x006f", _) => Ok(TPUChip {
                name: "v6e".to_string(),
                hbm_gib: 32,
                devices_per_chip: 1,
            }),
            _ => Err("Unknown TPU chip"),
        }
    }
}
