//! What the launcher and the scheduler say about the devices of a job.

use std::collections::HashMap;

use crate::wandb_internal::{AcceleratorMetrics, AcceleratorType, Binding};

/// The devices of the job a monitored process belongs to.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Job {
    /// The entries of CUDA_VISIBLE_DEVICES, when the launcher set it.
    visible_devices: Option<Vec<String>>,
    /// Whether the process runs in a Kubernetes pod, which sees only the
    /// devices assigned to it.
    pod: bool,
}

impl Job {
    /// The job of the process with `pid`, from its environment.
    pub fn of(pid: u32) -> Self {
        Self::from_environment(&environment(pid))
    }

    fn from_environment(environment: &HashMap<String, String>) -> Self {
        Self {
            visible_devices: environment.get("CUDA_VISIBLE_DEVICES").map(|list| {
                list.split(',')
                    .map(|entry| entry.trim().to_string())
                    .filter(|entry| !entry.is_empty())
                    .collect()
            }),
            // A pod that is a Slurm node holds the devices of every job on
            // it, so there only the device list says which are this job's.
            pod: environment.contains_key("KUBERNETES_SERVICE_HOST")
                && !environment.contains_key("SLURM_JOB_ID"),
        }
    }

    /// How `device` relates to the job when none of its processes is on it.
    pub fn binding(&self, device: &AcceleratorMetrics) -> Binding {
        if !device.host.is_empty() {
            // Another machine's device, as DCGM exporter reports them.
            return Binding::Unspecified;
        }
        if device.r#type() == AcceleratorType::NvidiaGpu && self.names(device) {
            return Binding::VisibleDevices;
        }
        if self.pod {
            Binding::Scheduler
        } else {
            Binding::Visible
        }
    }

    /// Whether the device list names `device`, by uuid, uuid prefix or index.
    fn names(&self, device: &AcceleratorMetrics) -> bool {
        // ponytail: CUDA numbers devices fastest first unless
        // CUDA_DEVICE_ORDER=PCI_BUS_ID, and NVML numbers them by PCI bus, so
        // an index can name another device on a host with mixed GPU models.
        // Order by NVML's CUDA capability if such hosts show up.
        let index = device.index.to_string();
        self.visible_devices.iter().flatten().any(|entry| {
            if entry.starts_with("GPU-") || entry.starts_with("MIG-") {
                !device.uuid.is_empty() && device.uuid.starts_with(entry.as_str())
            } else {
                device.parent_uuid.is_empty() && *entry == index
            }
        })
    }
}

/// The environment the process with `pid` started with, or this process's
/// own, which it inherits from the process it monitors, where another's
/// cannot be read.
fn environment(pid: u32) -> HashMap<String, String> {
    #[cfg(target_os = "linux")]
    if let Ok(environ) = std::fs::read(format!("/proc/{pid}/environ")) {
        return environ
            .split(|byte| *byte == 0)
            .filter_map(|entry| std::str::from_utf8(entry).ok()?.split_once('='))
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect();
    }
    let _ = pid;
    std::env::vars().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn job(variables: &[(&str, &str)]) -> Job {
        Job::from_environment(
            &variables
                .iter()
                .map(|(name, value)| (name.to_string(), value.to_string()))
                .collect(),
        )
    }

    fn gpu(index: u32, uuid: &str) -> AcceleratorMetrics {
        AcceleratorMetrics {
            r#type: AcceleratorType::NvidiaGpu as i32,
            index,
            uuid: uuid.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn binds_devices_by_the_device_list_then_the_pod() {
        let listed = job(&[("CUDA_VISIBLE_DEVICES", "0, GPU-bb")]);
        assert_eq!(listed.binding(&gpu(0, "GPU-aa")), Binding::VisibleDevices);
        assert_eq!(listed.binding(&gpu(1, "GPU-bbcc")), Binding::VisibleDevices);
        assert_eq!(listed.binding(&gpu(2, "GPU-dd")), Binding::Visible);

        let pod = job(&[("KUBERNETES_SERVICE_HOST", "10.0.0.1")]);
        assert_eq!(pod.binding(&gpu(2, "GPU-dd")), Binding::Scheduler);
        let remote = AcceleratorMetrics {
            host: "node-9".to_string(),
            ..gpu(2, "GPU-dd")
        };
        assert_eq!(pod.binding(&remote), Binding::Unspecified);

        let slurm_node = job(&[
            ("KUBERNETES_SERVICE_HOST", "10.0.0.1"),
            ("SLURM_JOB_ID", "7"),
        ]);
        assert_eq!(slurm_node.binding(&gpu(2, "GPU-dd")), Binding::Visible);
    }
}
