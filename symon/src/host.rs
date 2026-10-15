//! Host metrics: memory, CPU, disk and network for the machine and a
//! process tree, read with sysinfo on every platform, plus the cgroup v2
//! limits and TCP counters that only procfs has (Linux). Scopes that ask
//! for host details also get the use of every core, the load averages,
//! uptime, swap, the CPU temperature and the process table.
//!
//! A reading that is missing skips the keys it feeds and is logged once.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use log::warn;
use sysinfo::{
    CpuRefreshKind, Disk, DiskRefreshKind, Disks, MemoryRefreshKind, Networks, Pid,
    ProcessRefreshKind, ProcessesToUpdate, System,
};

use crate::metrics::{self, Readings, Sample, Scope};
use crate::monitors::Collector;
use crate::wandb_internal::{
    CpuInfo, DiskInfo, EnvironmentRecord, GetMetadataRequest, MemoryInfo, ProcessStats,
};

const MIB: f64 = 1024.0 * 1024.0;
const GIB: f64 = MIB * 1024.0;

/// The host collector and the state it keeps between sweeps.
pub struct Host {
    /// Physical and logical CPU counts; 0 when unknown.
    cpus: (u32, u32),
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    system: System,
    disks: Disks,
    networks: Networks,
    /// The process sets of the previous sweep. sysinfo measures CPU use
    /// between two refreshes, so a set is reported from its second sweep on.
    seen: HashSet<Tree>,
    /// The cgroup limits of each monitored pid.
    cgroups: HashMap<u32, Option<Cgroup>>,
    /// nr_periods and nr_throttled of each cpu.stat at the previous sweep.
    cpu_stat: HashMap<PathBuf, (u64, u64)>,
}

/// A set of processes whose readings are summed.
#[derive(Clone, PartialEq, Eq, Hash)]
enum Tree {
    /// A monitored process, with or without its descendants.
    Process { pid: u32, descendants: bool },
    /// The wandb processes and their direct children.
    Wandb(Vec<u32>),
}

impl Tree {
    fn pids(&self, children: &HashMap<Pid, Vec<Pid>>) -> Vec<Pid> {
        match self {
            Tree::Process {
                pid,
                descendants: false,
            } => vec![Pid::from_u32(*pid)],
            Tree::Process {
                pid,
                descendants: true,
            } => descendants(children, Pid::from_u32(*pid)),
            Tree::Wandb(pids) => pids
                .iter()
                .flat_map(|pid| {
                    let pid = Pid::from_u32(*pid);
                    std::iter::once(pid).chain(children.get(&pid).into_iter().flatten().copied())
                })
                .collect(),
        }
    }
}

#[derive(Default)]
struct TreeReading {
    /// Whether the first process of the set exists.
    root: bool,
    rss: u64,
    /// CPU use since the previous sweep in percent of one core.
    cpu: f64,
    threads: u64,
}

/// The cgroup v2 limits that apply to a process.
struct Cgroup {
    dir: PathBuf,
    /// The finite memory.max, if any.
    memory_limit: Option<u64>,
    /// The CPUs the process may use; 0 when nothing limits them.
    cpu_limit: f64,
    /// Whether cpu.max sets a quota, which is what throttles.
    cpu_quota: bool,
}

impl Host {
    pub fn new() -> Self {
        // Reading /proc/<pid>/stat on demand beats keeping half the fd limit open.
        sysinfo::set_open_files_limit(0);
        let mut system = System::new();
        // Taking the per-core usage baseline here gives the first sweep that
        // asks for host details a real reading instead of zeros.
        system.refresh_cpu_list(CpuRefreshKind::nothing().with_cpu_usage());
        let cpus = (
            System::physical_core_count().unwrap_or(0) as u32,
            system.cpus().len() as u32,
        );
        Self {
            cpus,
            state: Mutex::new(State {
                system,
                ..Default::default()
            }),
        }
    }

    /// Reads the host once and each scope's processes, cgroup and disks once.
    pub fn sweep(&self, scopes: &[Scope]) -> Sample {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let State {
            system,
            disks,
            networks,
            seen,
            cgroups,
            cpu_stat,
        } = &mut *state;
        let (physical, logical) = self.cpus;
        let host_details = scopes.iter().any(|scope| scope.host_details);
        // The Apple collector reports swap on Apple Silicon.
        let swap = host_details && !cfg!(all(target_os = "macos", target_arch = "aarch64"));

        refresh(system, disks, networks, host_details, swap);
        let total = system.total_memory();
        let available = available_memory().unwrap_or_else(|| system.available_memory());
        let children = children(system);

        let mut sample = Sample {
            counters: network_counters(networks),
            processes: if host_details {
                processes(system)
            } else {
                Vec::new()
            },
            ..Default::default()
        };
        let details = if host_details {
            host_details_metrics(system, swap)
        } else {
            Vec::new()
        };
        let mut next_cgroups = HashMap::new();
        let mut next_cpu_stat = HashMap::new();
        let mut trees: HashMap<Tree, TreeReading> = HashMap::new();

        for scope in scopes {
            let mut readings = Readings::default();
            let cgroup_pid = if scope.pid > 0 {
                scope.pid
            } else {
                std::process::id()
            };
            let cgroup = (!scope.disable_cgroup)
                .then(|| {
                    next_cgroups
                        .entry(cgroup_pid)
                        .or_insert_with(|| {
                            cgroups.remove(&cgroup_pid).unwrap_or_else(|| {
                                detect_cgroup(Path::new("/proc"), cgroup_pid, logical)
                            })
                        })
                        .as_ref()
                })
                .flatten();

            let denominator = memory_readings(cgroup, total, available, &mut readings);
            let capacity = cgroup
                .map(|cgroup| cgroup.cpu_limit)
                .filter(|limit| *limit > 0.0)
                .or((physical > 0).then_some(physical as f64));
            if let Some(cgroup) = cgroup {
                cgroup_readings(cgroup, cpu_stat, &mut next_cpu_stat, &mut readings);
            }
            process_readings(
                scope,
                system,
                &children,
                &mut trees,
                seen,
                denominator,
                capacity,
                &mut readings,
            );
            disk_readings(scope, disks, &mut readings);

            if scope.host_details {
                readings.metrics.extend(details.iter().cloned());
            }

            sample.scoped.insert(scope.clone(), readings);
        }

        *seen = trees.into_keys().collect();
        *cgroups = next_cgroups;
        *cpu_stat = next_cpu_stat;
        sample
    }

    /// Adds the memory size, CPU counts and the size and usage of the file
    /// systems at `disk_paths` to `metadata`.
    fn probe_host(&self, disk_paths: &[String], metadata: &mut EnvironmentRecord) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        state
            .system
            .refresh_memory_specifics(MemoryRefreshKind::nothing().with_ram());
        state
            .disks
            .refresh_specifics(true, DiskRefreshKind::nothing().with_storage());
        metadata.memory = Some(MemoryInfo {
            total: state.system.total_memory(),
        });
        (metadata.cpu_count, metadata.cpu_count_logical) = self.cpus;
        for path in disk_paths {
            if let Some(usage) = usage(&state.disks, path) {
                metadata.disk.insert(
                    path.clone(),
                    DiskInfo {
                        total: usage.total,
                        used: usage.used,
                    },
                );
            }
        }
    }
}

#[async_trait::async_trait]
impl Collector for Host {
    async fn collect_metrics(
        &self,
        scopes: &[Scope],
    ) -> Result<Sample, Box<dyn std::error::Error>> {
        if scopes.is_empty() {
            return Ok(Sample::default());
        }
        Ok(tokio::task::block_in_place(|| self.sweep(scopes)))
    }

    /// The CPU model, such as "Apple M4 Max".
    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        let state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let model = state.system.cpus().first().map(|cpu| cpu.brand().trim());
        EnvironmentRecord {
            cpu: model
                .filter(|model| !model.is_empty())
                .map(|model| CpuInfo {
                    model: model.to_string(),
                    ..Default::default()
                }),
            ..Default::default()
        }
    }

    async fn probe(&self, request: &GetMetadataRequest, metadata: &mut EnvironmentRecord) {
        self.probe_host(&request.disk_paths, metadata);
    }
}

// ===== One sweep, step by step =====

/// Refreshes what sysinfo caches: memory (and swap when asked), every
/// process, the disks and the network interfaces.
fn refresh(
    system: &mut System,
    disks: &mut Disks,
    networks: &mut Networks,
    host_details: bool,
    swap: bool,
) {
    let mut memory = MemoryRefreshKind::nothing().with_ram();
    if swap {
        memory = memory.with_swap();
    }
    system.refresh_memory_specifics(memory);
    // Before the processes: their refresh starts sysinfo's 200 ms cool-down
    // on the CPU totals, which would skip the per-core update.
    if host_details {
        system.refresh_cpu_usage();
    }
    system.refresh_processes_specifics(
        ProcessesToUpdate::All,
        true,
        ProcessRefreshKind::nothing()
            .with_cpu()
            .with_memory()
            .without_tasks(),
    );
    disks.refresh_specifics(
        true,
        DiskRefreshKind::nothing().with_storage().with_io_usage(),
    );
    networks.refresh(true);
}

/// Reports `memory_percent` and `proc.memory.availableMB` against the cgroup's
/// memory limit when it has one, else against the host, and returns the
/// denominator for `proc.memory.percent`.
fn memory_readings(
    cgroup: Option<&Cgroup>,
    total: u64,
    available: u64,
    readings: &mut Readings,
) -> u64 {
    let cgroup_memory = cgroup.and_then(|cgroup| {
        let limit = cgroup.memory_limit?;
        let current = read_u64(&cgroup.dir.join("memory.current"))?;
        Some((current, limit))
    });
    match cgroup_memory {
        Some((current, limit)) => {
            readings.metric("memory_percent", current as f64 / limit as f64 * 100.0);
            readings.metric(
                "proc.memory.availableMB",
                limit.saturating_sub(current) as f64 / MIB,
            );
            limit
        }
        None => {
            readings.metric(
                "memory_percent",
                total.saturating_sub(available) as f64 / total as f64 * 100.0,
            );
            readings.metric("proc.memory.availableMB", available as f64 / MIB);
            total
        }
    }
}

/// Reports the cgroup's CPU throttling since the previous sweep and its OOM
/// kills.
fn cgroup_readings(
    cgroup: &Cgroup,
    cpu_stat: &HashMap<PathBuf, (u64, u64)>,
    next_cpu_stat: &mut HashMap<PathBuf, (u64, u64)>,
    readings: &mut Readings,
) {
    if cgroup.cpu_quota {
        let path = cgroup.dir.join("cpu.stat");
        if let Some(values) = read_key_values(&path)
            && let (Some(&periods), Some(&throttled)) =
                (values.get("nr_periods"), values.get("nr_throttled"))
        {
            if let Some(&(last_periods, last_throttled)) = cpu_stat.get(&path)
                && periods > last_periods
                && throttled >= last_throttled
            {
                readings.average(
                    "proc.cpu.throttledPercent",
                    (throttled - last_throttled) as f64 / (periods - last_periods) as f64 * 100.0,
                );
            }
            next_cpu_stat.insert(path, (periods, throttled));
        }
    }
    if let Some(kills) = read_key_values(&cgroup.dir.join("memory.events"))
        .and_then(|values| values.get("oom_kill").copied())
    {
        readings.counter("proc.memory.oomKills", kills as f64);
    }
}

/// Reports the monitored process, with its descendants when asked, and the
/// wandb processes with their children. CPU use is divided by `capacity`.
#[allow(clippy::too_many_arguments)]
fn process_readings(
    scope: &Scope,
    system: &System,
    children: &HashMap<Pid, Vec<Pid>>,
    trees: &mut HashMap<Tree, TreeReading>,
    seen: &HashSet<Tree>,
    denominator: u64,
    capacity: Option<f64>,
    readings: &mut Readings,
) {
    let normalized = |cpu: f64| capacity.map_or(cpu, |capacity| cpu / capacity);
    if scope.pid > 0 {
        readings.pids = descendants(children, Pid::from_u32(scope.pid))
            .into_iter()
            .map(Pid::as_u32)
            .collect();
        let tree = Tree::Process {
            pid: scope.pid,
            descendants: scope.track_process_tree,
        };
        let reading = trees
            .entry(tree.clone())
            .or_insert_with(|| read_tree(system, &tree.pids(children)));
        if reading.root {
            readings.metric("proc.memory.rssMB", reading.rss as f64 / MIB);
            readings.metric(
                "proc.memory.percent",
                reading.rss as f64 / denominator as f64 * 100.0,
            );
            if reading.threads > 0 {
                readings.metric("proc.cpu.threads", reading.threads as f64);
            }
            if seen.contains(&tree) {
                readings.average("cpu", normalized(reading.cpu));
            }
        } else {
            skip("process");
        }
    }

    if !scope.wandb_pids.is_empty() {
        let tree = Tree::Wandb(scope.wandb_pids.clone());
        let reading = trees
            .entry(tree.clone())
            .or_insert_with(|| read_tree(system, &tree.pids(children)));
        readings.metric("wandb.memory.rssMB", reading.rss as f64 / MIB);
        if seen.contains(&tree) {
            readings.average("wandb.cpu", normalized(reading.cpu));
        }
    }
}

/// Reports the usage of each requested path and the bytes read and written
/// by the devices behind them.
fn disk_readings(scope: &Scope, disks: &Disks, readings: &mut Readings) {
    let mut devices = BTreeMap::new();
    for path in &scope.disk_paths {
        match usage(disks, path) {
            Some(usage) => {
                readings.metric(format!("disk.{path}.usagePercent"), usage.used_percent());
                readings.metric(format!("disk.{path}.usageGB"), usage.used as f64 / GIB);
            }
            None => skip("disk usage"),
        }
        // Every file system on the way to the path, as gopsutil did.
        for disk in disks_holding(disks, path) {
            let name = disk.name().to_string_lossy();
            if cfg!(target_os = "linux") && name == "/dev/root" {
                // The kernel's name for the root device, which has no
                // entry under /sys/block; cloud images mount / this way.
                if let Some(root) = root_device(disk.mount_point())
                    && let Some(&io) = block_devices().get(&root)
                {
                    devices.insert(root, io);
                }
            } else if cfg!(target_os = "linux")
                && (!name.starts_with("/dev/") || !Path::new(&*name).exists())
            {
                // No block device behind it, as with a container's
                // overlay root: watch every real device instead.
                devices.extend(block_devices());
            } else {
                let io = disk.usage();
                devices.insert(device(disk), (io.total_read_bytes, io.total_written_bytes));
            }
        }
    }
    for (device, (read, written)) in devices {
        readings.counter(format!("disk.{device}.in"), read as f64 / MIB);
        readings.counter(format!("disk.{device}.out"), written as f64 / MIB);
    }
}

// ===== Host details =====

/// The host-wide readings wandb leet symon shows: the use of every core
/// since the previous sweep, the load averages, uptime, swap when `swap`
/// and, on Linux, the CPU temperature.
fn host_details_metrics(system: &System, swap: bool) -> Vec<(String, f64)> {
    let mut details: Vec<(String, f64)> = system
        .cpus()
        .iter()
        .enumerate()
        .map(|(i, cpu)| (format!("cpu.{i}.cpu_percent"), f64::from(cpu.cpu_usage())))
        .collect();
    // sysinfo has no load average on Windows.
    if !cfg!(target_os = "windows") {
        let load = System::load_average();
        details.push(("system.load1".into(), load.one));
        details.push(("system.load5".into(), load.five));
        details.push(("system.load15".into(), load.fifteen));
    }
    details.push(("system.uptime".into(), System::uptime() as f64));
    if swap {
        let (used, total) = (system.used_swap(), system.total_swap());
        let percent = if total > 0 {
            used as f64 / total as f64 * 100.0
        } else {
            0.0
        };
        details.push(("swap.used".into(), used as f64));
        details.push(("swap.used_percent".into(), percent));
    }
    #[cfg(target_os = "linux")]
    {
        let components = sysinfo::Components::new_with_refreshed_list();
        let sensors = components
            .list()
            .iter()
            .filter_map(|component| Some((component.label(), component.temperature()?)));
        if let Some(temp) = cpu_temperature(sensors).or_else(thermal_zone_temperature) {
            details.push(("cpu.avg_temp".into(), temp));
        }
    }
    details
}

/// hwmon sensors that read the CPU temperature, by the lowercased label
/// with spaces as underscores, most representative first: the package or
/// die, then Tctl, then the individual cores or dies.
#[cfg(any(target_os = "linux", test))]
const CPU_SENSORS: [&[&str]; 3] = [
    &["coretemp_package_id_", "k10temp_tdie", "zenpower_tdie"],
    &["k10temp_tctl", "zenpower_tctl"],
    &["coretemp_core_", "k10temp_tccd", "zenpower_tccd"],
];

/// The mean of the most representative CPU temperature sensors among the
/// `(label, celsius)` readings. Readings at or below 0 or above 150 are
/// skipped: hwmon reports such values for absent or broken sensors.
#[cfg(any(target_os = "linux", test))]
fn cpu_temperature<'a>(sensors: impl Iterator<Item = (&'a str, f32)>) -> Option<f64> {
    let sensors: Vec<(String, f64)> = sensors
        .filter(|(_, temp)| *temp > 0.0 && *temp <= 150.0)
        .map(|(label, temp)| (label.to_lowercase().replace(' ', "_"), f64::from(temp)))
        .collect();
    CPU_SENSORS.iter().find_map(|prefixes| {
        let temps: Vec<f64> = sensors
            .iter()
            .filter(|(label, _)| prefixes.iter().any(|prefix| label.starts_with(prefix)))
            .map(|(_, temp)| *temp)
            .collect();
        (!temps.is_empty()).then(|| temps.iter().sum::<f64>() / temps.len() as f64)
    })
}

/// The mean of the SoC thermal zones that read the CPU, for boards without
/// hwmon CPU sensors.
#[cfg(target_os = "linux")]
fn thermal_zone_temperature() -> Option<f64> {
    const CPU_ZONES: [&str; 4] = ["cpu_thermal", "cpu-thermal", "x86_pkg_temp", "soc_thermal"];
    let temps: Vec<f64> = fs::read_dir("/sys/class/thermal")
        .ok()?
        .flatten()
        .map(|zone| zone.path())
        .filter(|zone| {
            fs::read_to_string(zone.join("type")).is_ok_and(|kind| CPU_ZONES.contains(&kind.trim()))
        })
        .filter_map(|zone| {
            fs::read_to_string(zone.join("temp"))
                .ok()?
                .trim()
                .parse::<f64>()
                .ok()
        })
        .map(|millidegrees| millidegrees / 1000.0)
        .filter(|temp| *temp > 0.0 && *temp <= 150.0)
        .collect();
    (!temps.is_empty()).then(|| temps.iter().sum::<f64>() / temps.len() as f64)
}

/// Every process whose memory the user can read. A process seen for the
/// first time has no CPU share yet.
fn processes(system: &System) -> Vec<ProcessStats> {
    system
        .processes()
        .values()
        .filter(|process| process.memory() > 0)
        .map(|process| ProcessStats {
            pid: process.pid().as_u32() as i32,
            name: process.name().to_string_lossy().into_owned(),
            cpu_percent: f64::from(process.cpu_usage()),
            rss_bytes: process.memory(),
        })
        .collect()
}

/// Logs once that a family of metrics cannot be read.
fn skip(family: &'static str) {
    static LOGGED: Mutex<Vec<&'static str>> = Mutex::new(Vec::new());
    let mut logged = LOGGED.lock().unwrap_or_else(|e| e.into_inner());
    if !logged.contains(&family) {
        logged.push(family);
        warn!("{family} metrics are unavailable on this host");
    }
}

// ===== Memory =====

/// The free and inactive pages, which is what gopsutil counted as available
/// memory on macOS. sysinfo's available figure includes the active pages.
#[cfg(target_os = "macos")]
#[allow(deprecated)] // libc points at the mach2 crate for mach_host_self
fn available_memory() -> Option<u64> {
    let mut stats = std::mem::MaybeUninit::<libc::vm_statistics64>::uninit();
    let mut count = libc::HOST_VM_INFO64_COUNT;
    // SAFETY: host_statistics64 writes at most `count` integers into `stats`
    // and returns KERN_SUCCESS only when it filled them.
    let filled = unsafe {
        libc::host_statistics64(
            libc::mach_host_self(),
            libc::HOST_VM_INFO64,
            stats.as_mut_ptr().cast(),
            &mut count,
        ) == libc::KERN_SUCCESS
    };
    let stats = filled.then(|| unsafe { stats.assume_init() })?;
    let page = unsafe { libc::vm_page_size } as u64;
    Some((u64::from(stats.free_count) + u64::from(stats.inactive_count)) * page)
}

#[cfg(not(target_os = "macos"))]
fn available_memory() -> Option<u64> {
    None
}

// ===== Processes =====

/// The children of every process, from the parent each one reports.
fn children(system: &System) -> HashMap<Pid, Vec<Pid>> {
    let mut children: HashMap<Pid, Vec<Pid>> = HashMap::new();
    for (pid, process) in system.processes() {
        if let Some(parent) = process.parent() {
            children.entry(parent).or_default().push(*pid);
        }
    }
    children
}

/// A process and all of its descendants.
fn descendants(children: &HashMap<Pid, Vec<Pid>>, root: Pid) -> Vec<Pid> {
    let mut pids = vec![root];
    let mut i = 0;
    while i < pids.len() {
        for child in children.get(&pids[i]).into_iter().flatten() {
            if !pids.contains(child) {
                pids.push(*child);
            }
        }
        i += 1;
    }
    pids
}

fn read_tree(system: &System, pids: &[Pid]) -> TreeReading {
    let mut reading = TreeReading::default();
    for (i, pid) in pids.iter().enumerate() {
        let Some(process) = system.process(*pid) else {
            continue;
        };
        reading.root |= i == 0;
        reading.rss += process.memory();
        reading.cpu += f64::from(process.cpu_usage());
        reading.threads += threads(pid.as_u32()).unwrap_or(0);
    }
    reading
}

/// The thread count of a process, where the platform has a cheap way to read it.
#[cfg(target_os = "linux")]
fn threads(pid: u32) -> Option<u64> {
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    stat.rsplit_once(')')?
        .1
        .split_whitespace()
        .nth(17)?
        .parse()
        .ok()
}

#[cfg(target_os = "macos")]
fn threads(pid: u32) -> Option<u64> {
    let mut info = std::mem::MaybeUninit::<libc::proc_taskinfo>::uninit();
    let size = std::mem::size_of::<libc::proc_taskinfo>() as libc::c_int;
    // SAFETY: proc_pidinfo writes at most `size` bytes into `info` and
    // returns how many it wrote; `info` is only read when it was filled.
    let written = unsafe {
        libc::proc_pidinfo(
            pid as libc::c_int,
            libc::PROC_PIDTASKINFO,
            0,
            info.as_mut_ptr().cast(),
            size,
        )
    };
    (written == size).then(|| unsafe { info.assume_init() }.pti_threadnum as u64)
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn threads(_pid: u32) -> Option<u64> {
    None
}

// ===== cgroup v2 =====

/// The limits of the leaf cgroup that holds `pid`, or None when neither its
/// memory nor its CPUs are limited.
fn detect_cgroup(proc_root: &Path, pid: u32, logical_cpus: u32) -> Option<Cgroup> {
    let pid_dir = proc_root.join(pid.to_string());
    let cgroup_path = fs::read_to_string(pid_dir.join("cgroup"))
        .ok()?
        .lines()
        .find_map(|line| {
            let mut parts = line.splitn(3, ':');
            let (_, controllers, path) = (parts.next()?, parts.next()?, parts.next()?);
            controllers.is_empty().then(|| path.to_string())
        })?;
    let mountinfo = fs::read_to_string(pid_dir.join("mountinfo")).ok()?;
    let (root, mount_point) = mountinfo.lines().find_map(|line| {
        let (mount, filesystem) = line.split_once(" - ")?;
        let mut fields = mount.split_whitespace().skip(3);
        let (root, mount_point) = (fields.next()?, fields.next()?);
        filesystem
            .starts_with("cgroup2 ")
            .then_some((root, mount_point))
    })?;
    let dir = cgroup_dir(root, mount_point, &cgroup_path);

    let memory_limit = read_u64(&dir.join("memory.max")).filter(|limit| *limit > 0);
    let quota = cpu_quota_limit(&dir);
    let allowed = cpus_allowed(&pid_dir.join("status"))
        .filter(|allowed| *allowed > 0 && (logical_cpus == 0 || *allowed < logical_cpus))
        .map_or(0.0, |allowed| allowed as f64);
    let cpu_limit = match (quota > 0.0, allowed > 0.0) {
        (true, true) => quota.min(allowed),
        (true, false) => quota,
        (false, _) => allowed,
    };
    if memory_limit.is_none() && cpu_limit <= 0.0 {
        return None;
    }
    Some(Cgroup {
        dir,
        memory_limit,
        cpu_limit,
        cpu_quota: quota > 0.0,
    })
}

/// The directory of `cgroup_path` under a cgroup2 mount of `root`, which may
/// be a bind mount of a subtree of the hierarchy.
fn cgroup_dir(root: &str, mount_point: &str, cgroup_path: &str) -> PathBuf {
    let root = root.trim_end_matches('/');
    let mut rel = cgroup_path.trim_end_matches('/');
    if !root.is_empty() {
        if rel == root {
            rel = "";
        } else if let Some(stripped) = rel.strip_prefix(root)
            && stripped.starts_with('/')
        {
            rel = stripped;
        }
    }
    Path::new(mount_point).join(rel.trim_start_matches('/'))
}

/// The CPUs cpu.max grants, quota over period, or 0 without a quota.
fn cpu_quota_limit(dir: &Path) -> f64 {
    let Ok(text) = fs::read_to_string(dir.join("cpu.max")) else {
        return 0.0;
    };
    let fields: Vec<&str> = text.split_whitespace().collect();
    let [quota, period] = fields[..] else {
        return 0.0;
    };
    match (quota.parse::<u64>(), period.parse::<u64>()) {
        (Ok(quota), Ok(period)) if quota > 0 && period > 0 => quota as f64 / period as f64,
        _ => 0.0,
    }
}

/// The number of CPUs in the Cpus_allowed_list of a status file.
fn cpus_allowed(status: &Path) -> Option<u32> {
    let text = fs::read_to_string(status).ok()?;
    let list = text
        .lines()
        .find_map(|line| line.strip_prefix("Cpus_allowed_list:"))?;
    let mut count = 0;
    for range in list.split(',') {
        let range = range.trim();
        count += match range.split_once('-') {
            Some((start, end)) => {
                let (start, end) = (start.parse::<u32>().ok()?, end.parse::<u32>().ok()?);
                end.saturating_sub(start) + 1
            }
            None => u32::from(!range.is_empty()),
        };
    }
    Some(count)
}

/// A cgroup file holding one number, or None when it holds `max`.
fn read_u64(path: &Path) -> Option<u64> {
    fs::read_to_string(path).ok()?.trim().parse().ok()
}

/// A cgroup file of `key value` lines, such as cpu.stat or memory.events.
fn read_key_values(path: &Path) -> Option<HashMap<String, u64>> {
    let text = fs::read_to_string(path).ok()?;
    Some(
        text.lines()
            .filter_map(|line| {
                let (key, value) = line.split_once(' ')?;
                Some((key.to_string(), value.trim().parse().ok()?))
            })
            .collect(),
    )
}

// ===== Network =====

/// Bytes sent and received over the interfaces that are not loopback and
/// not enslaved to a bond, bridge or team master, which reports them.
fn network_counters(networks: &Networks) -> Vec<(String, f64)> {
    let (mut sent, mut recv) = (0u64, 0u64);
    for (name, data) in networks.list() {
        if name.starts_with("lo")
            || Path::new("/sys/class/net")
                .join(name)
                .join("master")
                .exists()
        {
            continue;
        }
        sent += data.total_transmitted();
        recv += data.total_received();
    }
    let mut counters = vec![
        ("network.sent".to_string(), sent as f64),
        ("network.recv".to_string(), recv as f64),
    ];
    if let Some(retransmits) = tcp_retransmits() {
        counters.push(("network.tcpRetransmits".to_string(), retransmits as f64));
    }
    counters
}

/// The RetransSegs counter of the Tcp line of /proc/net/snmp.
fn tcp_retransmits() -> Option<u64> {
    let text = fs::read_to_string("/proc/net/snmp").ok()?;
    let mut lines = text.lines();
    while let Some(header) = lines.next() {
        let values = lines.next()?;
        let (Some(names), Some(values)) =
            (header.strip_prefix("Tcp:"), values.strip_prefix("Tcp:"))
        else {
            continue;
        };
        let index = names
            .split_whitespace()
            .position(|name| name == "RetransSegs")?;
        return values.split_whitespace().nth(index)?.parse().ok();
    }
    None
}

// ===== Disks =====

struct DiskUsage {
    total: u64,
    used: u64,
    free: u64,
}

impl DiskUsage {
    fn used_percent(&self) -> f64 {
        match self.used + self.free {
            0 => 0.0,
            capacity => self.used as f64 / capacity as f64 * 100.0,
        }
    }
}

/// The size and usage of the file system holding `path`, as gopsutil
/// reported them: the blocks in use against the blocks a user can still fill.
#[cfg(unix)]
fn usage(_disks: &Disks, path: &str) -> Option<DiskUsage> {
    let stat = nix::sys::statfs::statfs(path).ok()?;
    let block = stat.block_size() as u64;
    let blocks = stat.blocks() as u64;
    Some(DiskUsage {
        total: blocks * block,
        used: blocks.saturating_sub(stat.blocks_free() as u64) * block,
        free: stat.blocks_available() as u64 * block,
    })
}

#[cfg(not(unix))]
fn usage(disks: &Disks, path: &str) -> Option<DiskUsage> {
    let path = canonical(path)?;
    let disk = disks
        .list()
        .iter()
        .filter(|disk| path.starts_with(disk.mount_point()))
        .max_by_key(|disk| disk.mount_point().as_os_str().len())?;
    let (total, free) = (disk.total_space(), disk.available_space());
    Some(DiskUsage {
        total,
        used: total.saturating_sub(free),
        free,
    })
}

/// The disks whose mount points are prefixes of `path`.
fn disks_holding<'a>(disks: &'a Disks, path: &str) -> Vec<&'a Disk> {
    let Some(path) = canonical(path) else {
        return Vec::new();
    };
    disks
        .list()
        .iter()
        .filter(|disk| path.starts_with(disk.mount_point()))
        .collect()
}

/// The canonical form of `path` without the verbatim prefix Windows adds.
fn canonical(path: &str) -> Option<PathBuf> {
    let canonical = fs::canonicalize(path).ok()?;
    let canonical = canonical.to_str()?;
    Some(PathBuf::from(
        canonical.strip_prefix(r"\\?\").unwrap_or(canonical),
    ))
}

/// The device behind a disk: the kernel name of its block device, else
/// its volume name, else its mount point.
fn device(disk: &Disk) -> String {
    let name = disk.name().to_string_lossy();
    if let Some(device) = name.strip_prefix("/dev/") {
        let real = fs::canonicalize(&*name).unwrap_or_else(|_| PathBuf::from(&*name));
        let real = real.to_string_lossy();
        return real.strip_prefix("/dev/").unwrap_or(device).to_string();
    }
    if name.is_empty() {
        return disk.mount_point().to_string_lossy().into_owned();
    }
    name.into_owned()
}

/// Bytes read and written by every real block device, from /proc/diskstats.
#[cfg(target_os = "linux")]
fn block_devices() -> BTreeMap<String, (u64, u64)> {
    const SECTOR: u64 = 512;
    fs::read_to_string("/proc/diskstats")
        .unwrap_or_default()
        .lines()
        .filter_map(|line| {
            let fields: Vec<&str> = line.split_whitespace().collect();
            let name = *fields.get(2)?;
            let pseudo = ["loop", "ram", "zram"].iter().any(|p| name.starts_with(p));
            if pseudo || fields.len() < 14 || fields[3..14].iter().all(|f| *f == "0") {
                return None;
            }
            let read = fields[5].parse::<u64>().ok()? * SECTOR;
            let written = fields[9].parse::<u64>().ok()? * SECTOR;
            Some((name.to_string(), (read, written)))
        })
        .collect()
}

#[cfg(not(target_os = "linux"))]
fn block_devices() -> BTreeMap<String, (u64, u64)> {
    BTreeMap::new()
}

/// The block device mounted at `mount_point`, named by the kernel: its
/// major:minor from mountinfo resolved through /sys/dev/block, as gopsutil
/// did for mounts that /proc/mounts calls /dev/root.
#[cfg(target_os = "linux")]
fn root_device(mount_point: &Path) -> Option<String> {
    let mountinfo = fs::read_to_string("/proc/self/mountinfo").ok()?;
    let id = mountinfo.lines().find_map(|line| {
        let fields: Vec<&str> = line.split_whitespace().collect();
        (Path::new(fields.get(4)?) == mount_point).then(|| fields[2].to_string())
    })?;
    let link = fs::read_link(Path::new("/sys/dev/block").join(id)).ok()?;
    Some(link.file_name()?.to_string_lossy().into_owned())
}

#[cfg(not(target_os = "linux"))]
fn root_device(_mount_point: &Path) -> Option<String> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn value(readings: &Readings, key: &str) -> Option<f64> {
        [&readings.metrics, &readings.averages, &readings.counters]
            .into_iter()
            .flatten()
            .find(|(k, _)| k == key)
            .map(|(_, v)| *v)
    }

    #[test]
    fn cgroup_limits_come_from_the_leaf_cgroup() {
        let dir = tempfile::tempdir().unwrap();
        let write = |rel: &str, text: &str| {
            let path = dir.path().join(rel);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        };
        let cgroup = dir.path().join("sys/fs/cgroup");
        write("1/cgroup", "0::/kubepods/pod123/container456\n");
        write(
            "1/mountinfo",
            &format!(
                "1 0 0:1 /kubepods {} rw,relatime - cgroup2 cgroup rw\n",
                cgroup.display()
            ),
        );
        write("1/status", "Name:\tpython\nCpus_allowed_list:\t0-1,3\n");
        write(
            "sys/fs/cgroup/pod123/container456/memory.max",
            "8589934592\n",
        );
        write(
            "sys/fs/cgroup/pod123/container456/cpu.max",
            "400000 100000\n",
        );

        let limits = detect_cgroup(dir.path(), 1, 8).unwrap();
        assert_eq!(limits.dir, cgroup.join("pod123/container456"));
        assert_eq!(limits.memory_limit, Some(8 << 30));
        assert_eq!(limits.cpu_limit, 3.0);
        assert!(limits.cpu_quota);
        assert!(detect_cgroup(dir.path(), 2, 8).is_none());
    }

    #[test]
    fn cpu_temperature_prefers_the_package_sensor_and_skips_bad_readings() {
        let temp = |sensors: &[(&str, f32)]| cpu_temperature(sensors.iter().copied());
        assert_eq!(
            temp(&[
                ("coretemp Package id 0", 60.0),
                ("coretemp Core 0", 50.0),
                ("coretemp Core 1", 70.0),
                ("nvme Composite", 40.0),
            ]),
            Some(60.0)
        );
        assert_eq!(
            temp(&[("k10temp Tctl", 0.0), ("k10temp Tccd1", 55.0)]),
            Some(55.0)
        );
        assert_eq!(temp(&[("acpitz temp1", 45.0)]), None);
    }

    #[test]
    fn the_host_reports_its_own_process() {
        let host = Host::new();
        let scope = Scope {
            pid: std::process::id(),
            host_details: true,
            ..Default::default()
        };
        let first = host.sweep(std::slice::from_ref(&scope));
        let readings = &first.scoped[&scope];
        assert!(value(readings, "proc.memory.rssMB").unwrap() > 0.0);
        let percent = value(readings, "memory_percent").unwrap();
        assert!(percent > 0.0 && percent <= 100.0);
        assert_eq!(value(readings, "cpu"), None);

        std::thread::sleep(Duration::from_millis(300));
        let second = host.sweep(std::slice::from_ref(&scope));
        assert!(value(&second.scoped[&scope], "cpu").is_some());
        assert!(value(&second.scoped[&scope], "cpu.0.cpu_percent").is_some());
        assert!(!second.processes.is_empty());
    }
}
