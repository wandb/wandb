use serde::Serialize;
use sysinfo::{CpuRefreshKind, RefreshKind, System as SysInfo};

// use crate::{metrics::MetricValue, wandb_internal::MetadataRequest};
use crate::{metrics::MetricValue, pid::process_tree};

#[derive(Debug, Default, Clone, Serialize)]
struct SystemStats {
    // Global CPU utilization as a percentage.
    cpu_utilization: f64,
    // CPU utilization per core as a percentage.
    cpu_utilization_per_core: Vec<f64>,
    // Load averages for the last 1, 5, and 15 minutes.
    load_avg: (f64, f64, f64),
}

impl SystemStats {
    pub fn to_vec(&self) -> Vec<(String, MetricValue)> {
        let mut metrics = vec![
            ("cpu".to_string(), MetricValue::Float(self.cpu_utilization)),
            (
                "_cpu.load_avg.1m".to_string(),
                MetricValue::Float(self.load_avg.0),
            ),
            (
                "_cpu.load_avg.5m".to_string(),
                MetricValue::Float(self.load_avg.1),
            ),
            (
                "_cpu.load_avg.15m".to_string(),
                MetricValue::Float(self.load_avg.2),
            ),
        ];

        metrics.extend(
            self.cpu_utilization_per_core
                .iter()
                .enumerate()
                .map(|(i, &value)| (format!("cpu.{}.cpu_percent", i), MetricValue::Float(value))),
        );

        metrics
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
        println!("pid: {}", self.pid);
        let descendant_pids = process_tree(self.pid)?;
        println!("descendant_pids: {:?}", descendant_pids);

        let mut system_stats = SystemStats::default();

        // CPU load
        let load_avg = SysInfo::load_average();
        system_stats.load_avg = (load_avg.one, load_avg.five, load_avg.fifteen);

        // CPU utilization
        self.sys_info.refresh_cpu_all();
        for cpu in self.sys_info.cpus() {
            system_stats
                .cpu_utilization_per_core
                .push(cpu.cpu_usage() as f64);
        }
        system_stats.cpu_utilization = system_stats
            .cpu_utilization_per_core
            .iter()
            .fold(0.0, |acc, &x| acc + x)
            / system_stats.cpu_utilization_per_core.len() as f64;

        println!("{:?}", system_stats);

        Ok(system_stats.to_vec())
    }
}
