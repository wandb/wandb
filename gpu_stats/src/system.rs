use serde::Serialize;
use sysinfo::{CpuRefreshKind, RefreshKind, System as SysInfo};

use crate::{metrics::MetricValue, wandb_internal::MetadataRequest};

#[derive(Debug, Default, Clone, Serialize)]
struct SystemStats {
    cpu_utilization: f64,
}

impl SystemStats {
    pub fn to_vec(&self) -> Vec<(String, MetricValue)> {
        vec![("cpu".to_string(), MetricValue::Float(self.cpu_utilization))]
    }
}

#[derive(Default)]
pub struct System {
    pid: i32,
    sys_info: SysInfo,
    // TODO: static info like cpu brand and model
}

impl System {
    pub fn new(pid: i32) -> Self {
        let sys_info = SysInfo::new_with_specifics(
            RefreshKind::nothing().with_cpu(CpuRefreshKind::everything()),
        );
        // TODO: get static info
        Self { pid, sys_info }
    }

    pub fn get_metrics(&mut self) -> Result<Vec<(String, MetricValue)>, std::io::Error> {
        println!("{}", self.pid);

        let load_avg = SysInfo::load_average();

        println!(
            "one minute: {}%, five minutes: {}%, fifteen minutes: {}%",
            load_avg.one, load_avg.five, load_avg.fifteen,
        );

        self.sys_info.refresh_cpu_all();
        for cpu in self.sys_info.cpus() {
            println!("{}%", cpu.cpu_usage())
        }

        let stats = SystemStats {
            cpu_utilization: 0.0,
        };

        Ok(stats.to_vec())
    }
}
