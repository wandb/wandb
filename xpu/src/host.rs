//! Host metrics from procfs and sysfs: memory, CPU, disk and network for
//! the machine, a process tree and the cgroup v2 limits that apply to it.
//!
//! Every reader takes the procfs and sysfs roots, so fixture trees stand in
//! for the live files in tests. A file that is missing or unparsable skips
//! the keys it feeds and is logged once.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

use log::warn;

use crate::metrics::{Readings, Sample, Scope};
use crate::wandb_internal::{DiskInfo, EnvironmentRecord, MemoryInfo};

pub const PROC: &str = "/proc";
pub const SYS: &str = "/sys";

/// Clock ticks per second of the CPU times in procfs (USER_HZ).
const USER_HZ: f64 = 100.0;
const SECTOR_SIZE: u64 = 512;
const MIB: f64 = 1024.0 * 1024.0;
const GIB: f64 = MIB * 1024.0;
const IFF_LOOPBACK: u64 = 0x8;

/// The host collector and the state it keeps between sweeps.
pub struct Host {
    proc_root: PathBuf,
    sys_root: PathBuf,
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    /// Physical and logical CPU counts, read once.
    cpus: Option<(u32, u32)>,
    /// The cgroup limits of each monitored pid.
    cgroups: HashMap<u32, Option<Cgroup>>,
    /// The devices behind each requested list of disk paths.
    devices: HashMap<Vec<String>, Vec<String>>,
    /// CPU ticks of each process of each process set at the previous
    /// sweep, and when.
    ticks: HashMap<Tree, (HashMap<u32, u64>, Instant)>,
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
    fn pids(&self, proc_root: &Path) -> Vec<u32> {
        match self {
            Tree::Process {
                pid,
                descendants: false,
            } => vec![*pid],
            Tree::Process {
                pid,
                descendants: true,
            } => process_tree(proc_root, *pid),
            Tree::Wandb(pids) => pids
                .iter()
                .flat_map(|pid| std::iter::once(*pid).chain(children(proc_root, *pid)))
                .collect(),
        }
    }
}

#[derive(Default)]
struct TreeReading {
    /// Whether the first process of the set exists.
    root: bool,
    rss: u64,
    /// CPU ticks by pid.
    ticks: HashMap<u32, u64>,
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
    pub fn new(proc_root: impl Into<PathBuf>, sys_root: impl Into<PathBuf>) -> Self {
        Self {
            proc_root: proc_root.into(),
            sys_root: sys_root.into(),
            state: Mutex::new(State::default()),
        }
    }

    /// Reads the host once and each scope's processes, cgroup and disks
    /// once, at `now`.
    pub fn sweep(&self, scopes: &[Scope], now: Instant) -> Sample {
        let proc_root = &self.proc_root;
        let sys_root = &self.sys_root;
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let state = &mut *state;

        let mut sample = Sample {
            counters: network_counters(proc_root, sys_root),
            ..Default::default()
        };
        let meminfo = meminfo(proc_root);
        if meminfo.is_none() {
            skip("memory");
        }
        let diskstats = diskstats(proc_root).unwrap_or_else(|| {
            skip("disk I/O");
            HashMap::new()
        });
        let (physical, logical) = *state
            .cpus
            .get_or_insert_with(|| cpu_counts(proc_root, sys_root));

        let mut cgroups = HashMap::new();
        let mut devices = HashMap::new();
        let mut ticks = HashMap::new();
        let mut cpu_stat = HashMap::new();
        let mut trees: HashMap<Tree, TreeReading> = HashMap::new();
        let mut usages: HashMap<&str, Option<DiskUsage>> = HashMap::new();

        for scope in scopes {
            let mut readings = Readings::default();
            let cgroup_pid = if scope.pid > 0 {
                scope.pid
            } else {
                std::process::id()
            };
            let cgroup = (!scope.disable_cgroup)
                .then(|| {
                    cgroups
                        .entry(cgroup_pid)
                        .or_insert_with(|| {
                            state
                                .cgroups
                                .remove(&cgroup_pid)
                                .unwrap_or_else(|| detect_cgroup(proc_root, cgroup_pid, logical))
                        })
                        .as_ref()
                })
                .flatten();

            let cgroup_memory = cgroup.and_then(|cgroup| {
                let limit = cgroup.memory_limit?;
                let current = read_u64(&cgroup.dir.join("memory.current"))?;
                Some((current, limit))
            });
            let denominator = match (cgroup_memory, &meminfo) {
                (Some((current, limit)), _) => {
                    readings.metric("memory_percent", current as f64 / limit as f64 * 100.0);
                    readings.metric(
                        "proc.memory.availableMB",
                        limit.saturating_sub(current) as f64 / MIB,
                    );
                    Some(limit)
                }
                (None, Some(meminfo)) => {
                    readings.metric("memory_percent", meminfo.used_percent());
                    readings.metric("proc.memory.availableMB", meminfo.available as f64 / MIB);
                    Some(meminfo.total)
                }
                (None, None) => None,
            };

            let capacity = cgroup
                .map(|cgroup| cgroup.cpu_limit)
                .filter(|limit| *limit > 0.0)
                .or((physical > 0).then_some(physical as f64));

            if let Some(cgroup) = cgroup {
                if cgroup.cpu_quota {
                    let path = cgroup.dir.join("cpu.stat");
                    if let Some(values) = read_key_values(&path)
                        && let (Some(&periods), Some(&throttled)) =
                            (values.get("nr_periods"), values.get("nr_throttled"))
                    {
                        if let Some(&(last_periods, last_throttled)) = state.cpu_stat.get(&path)
                            && periods > last_periods
                            && throttled >= last_throttled
                        {
                            readings.average(
                                "proc.cpu.throttledPercent",
                                (throttled - last_throttled) as f64
                                    / (periods - last_periods) as f64
                                    * 100.0,
                            );
                        }
                        cpu_stat.insert(path, (periods, throttled));
                    }
                }
                if let Some(kills) = read_key_values(&cgroup.dir.join("memory.events"))
                    .and_then(|values| values.get("oom_kill").copied())
                {
                    readings.counter("proc.memory.oomKills", kills as f64);
                }
            }

            if scope.pid > 0 {
                let tree = Tree::Process {
                    pid: scope.pid,
                    descendants: scope.track_process_tree,
                };
                let reading = trees
                    .entry(tree.clone())
                    .or_insert_with(|| read_tree(proc_root, &tree.pids(proc_root)));
                if reading.root {
                    readings.metric("proc.memory.rssMB", reading.rss as f64 / MIB);
                    if let Some(denominator) = denominator {
                        readings.metric(
                            "proc.memory.percent",
                            reading.rss as f64 / denominator as f64 * 100.0,
                        );
                    }
                    readings.metric("proc.cpu.threads", reading.threads as f64);
                    if let Some(cpu) =
                        cpu_percent(state.ticks.get(&tree), &reading.ticks, now, capacity)
                    {
                        readings.average("cpu", cpu);
                    }
                    ticks.insert(tree, (reading.ticks.clone(), now));
                } else {
                    skip("process");
                }
            }

            if !scope.wandb_pids.is_empty() {
                let tree = Tree::Wandb(scope.wandb_pids.clone());
                let reading = trees
                    .entry(tree.clone())
                    .or_insert_with(|| read_tree(proc_root, &tree.pids(proc_root)));
                readings.metric("wandb.memory.rssMB", reading.rss as f64 / MIB);
                if let Some(cpu) =
                    cpu_percent(state.ticks.get(&tree), &reading.ticks, now, capacity)
                {
                    readings.average("wandb.cpu", cpu);
                }
                ticks.insert(tree, (reading.ticks.clone(), now));
            }

            for path in &scope.disk_paths {
                let usage = usages
                    .entry(path.as_str())
                    .or_insert_with(|| disk_usage(path));
                match usage {
                    Some(usage) => {
                        readings.metric(format!("disk.{path}.usagePercent"), usage.used_percent());
                        readings.metric(format!("disk.{path}.usageGB"), usage.used as f64 / GIB);
                    }
                    None => skip("disk usage"),
                }
            }
            let scope_devices = devices.entry(scope.disk_paths.clone()).or_insert_with(|| {
                state.devices.remove(&scope.disk_paths).unwrap_or_else(|| {
                    disk_devices(proc_root, sys_root, &scope.disk_paths, &diskstats)
                })
            });
            for device in scope_devices.iter() {
                if let Some(&(read, written)) = diskstats.get(device) {
                    readings.counter(format!("disk.{device}.in"), read as f64 / MIB);
                    readings.counter(format!("disk.{device}.out"), written as f64 / MIB);
                }
            }

            sample.scoped.insert(scope.clone(), readings);
        }

        state.cgroups = cgroups;
        state.devices = devices;
        state.ticks = ticks;
        state.cpu_stat = cpu_stat;
        sample
    }

    /// Adds the memory size, CPU counts and the size and usage of the file
    /// systems at `disk_paths` to `metadata`.
    pub fn probe(&self, disk_paths: &[String], metadata: &mut EnvironmentRecord) {
        if let Some(meminfo) = meminfo(&self.proc_root) {
            metadata.memory = Some(MemoryInfo {
                total: meminfo.total,
            });
        }
        let (physical, logical) = *self
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .cpus
            .get_or_insert_with(|| cpu_counts(&self.proc_root, &self.sys_root));
        metadata.cpu_count = physical;
        metadata.cpu_count_logical = logical;
        for path in disk_paths {
            if let Some(usage) = disk_usage(path) {
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

/// Logs once that a family of metrics cannot be read.
fn skip(family: &'static str) {
    static LOGGED: Mutex<Vec<&'static str>> = Mutex::new(Vec::new());
    let mut logged = LOGGED.lock().unwrap_or_else(|e| e.into_inner());
    if !logged.contains(&family) {
        logged.push(family);
        warn!("{family} metrics are unavailable on this host");
    }
}

/// CPU use of the processes in `ticks` since the previous sweep as a
/// percentage of one core, divided by `capacity` when known. A process
/// that was not there at the previous sweep counts from zero.
fn cpu_percent(
    previous: Option<&(HashMap<u32, u64>, Instant)>,
    ticks: &HashMap<u32, u64>,
    now: Instant,
    capacity: Option<f64>,
) -> Option<f64> {
    let (last_ticks, then) = previous?;
    let elapsed = now.duration_since(*then).as_secs_f64();
    if elapsed <= 0.0 {
        return None;
    }
    let used: u64 = ticks
        .iter()
        .map(|(pid, ticks)| ticks.saturating_sub(last_ticks.get(pid).copied().unwrap_or(0)))
        .sum();
    let percent = used as f64 / USER_HZ / elapsed * 100.0;
    Some(capacity.map_or(percent, |capacity| percent / capacity))
}

// ===== Processes =====

/// A process and all of its descendants, from `/proc/<pid>/task/*/children`.
pub fn process_tree(proc_root: &Path, pid: u32) -> Vec<u32> {
    let mut pids = vec![pid];
    let mut i = 0;
    while i < pids.len() {
        for child in children(proc_root, pids[i]) {
            if !pids.contains(&child) {
                pids.push(child);
            }
        }
        i += 1;
    }
    pids
}

/// The direct children of a process, forked from any of its threads.
fn children(proc_root: &Path, pid: u32) -> Vec<u32> {
    let Ok(tasks) = fs::read_dir(proc_root.join(pid.to_string()).join("task")) else {
        return Vec::new();
    };
    tasks
        .flatten()
        .filter_map(|task| fs::read_to_string(task.path().join("children")).ok())
        .flat_map(|children| {
            children
                .split_whitespace()
                .filter_map(|child| child.parse().ok())
                .collect::<Vec<u32>>()
        })
        .collect()
}

fn read_tree(proc_root: &Path, pids: &[u32]) -> TreeReading {
    let mut reading = TreeReading::default();
    for (i, pid) in pids.iter().enumerate() {
        let Some((ticks, threads, rss)) = read_process(proc_root, *pid) else {
            continue;
        };
        reading.root |= i == 0;
        reading.ticks.insert(*pid, ticks);
        reading.threads += threads;
        reading.rss += rss;
    }
    reading
}

/// A process's CPU ticks, thread count and resident set in bytes.
fn read_process(proc_root: &Path, pid: u32) -> Option<(u64, u64, u64)> {
    let dir = proc_root.join(pid.to_string());
    let stat = fs::read_to_string(dir.join("stat")).ok()?;
    let fields: Vec<&str> = stat.rsplit_once(')')?.1.split_whitespace().collect();
    let field = |n: usize| fields.get(n - 3)?.parse::<u64>().ok();
    let ticks = field(14)? + field(15)?;
    let threads = field(20)?;
    let rss = fs::read_to_string(dir.join("status"))
        .ok()
        .and_then(|status| {
            status
                .lines()
                .find_map(|line| line.strip_prefix("VmRSS:"))
                .and_then(parse_kb)
        })
        .unwrap_or(0);
    Some((ticks, threads, rss))
}

/// Parses a `<number> kB` value into bytes.
fn parse_kb(value: &str) -> Option<u64> {
    let kb: u64 = value.trim().trim_end_matches("kB").trim().parse().ok()?;
    Some(kb * 1024)
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
    let mounts = parse_mountinfo(&fs::read_to_string(pid_dir.join("mountinfo")).ok()?);
    let mount = mounts.iter().find(|mount| mount.fstype == "cgroup2")?;
    let dir = cgroup_dir(mount, &cgroup_path);

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

/// The directory of `cgroup_path` under a cgroup2 mount, which may be a
/// bind mount of a subtree of the hierarchy.
fn cgroup_dir(mount: &Mount, cgroup_path: &str) -> PathBuf {
    let root = mount.root.trim_end_matches('/');
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
    Path::new(&mount.mount_point).join(rel.trim_start_matches('/'))
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

// ===== Memory and CPUs =====

struct MemInfo {
    total: u64,
    available: u64,
}

impl MemInfo {
    fn used_percent(&self) -> f64 {
        self.total.saturating_sub(self.available) as f64 / self.total as f64 * 100.0
    }
}

/// Total and available memory from meminfo, with the kernel's MemAvailable
/// estimate when it has one.
fn meminfo(proc_root: &Path) -> Option<MemInfo> {
    let text = fs::read_to_string(proc_root.join("meminfo")).ok()?;
    let values: HashMap<&str, u64> = text
        .lines()
        .filter_map(|line| {
            let (key, value) = line.split_once(':')?;
            Some((key.trim(), parse_kb(value)?))
        })
        .collect();
    let value = |key| values.get(key).copied().unwrap_or(0);
    let total = value("MemTotal");
    if total == 0 {
        return None;
    }
    let available = values
        .get("MemAvailable")
        .copied()
        .unwrap_or_else(|| value("MemFree") + value("Cached") + value("SReclaimable"));
    Some(MemInfo { total, available })
}

/// The physical and logical CPU counts; 0 when unknown.
fn cpu_counts(proc_root: &Path, sys_root: &Path) -> (u32, u32) {
    let cpuinfo = fs::read_to_string(proc_root.join("cpuinfo")).unwrap_or_default();
    let mut logical = cpuinfo
        .lines()
        .filter(|line| {
            line.starts_with("processor")
                && line
                    .split_once(':')
                    .is_some_and(|(_, value)| value.trim().parse::<u32>().is_ok())
        })
        .count();
    if logical == 0 {
        logical = fs::read_to_string(proc_root.join("stat"))
            .unwrap_or_default()
            .lines()
            .filter(|line| {
                line.strip_prefix("cpu")
                    .is_some_and(|rest| rest.starts_with(|c: char| c.is_ascii_digit()))
            })
            .count();
    }
    let physical = physical_cpus(sys_root).unwrap_or_else(|| physical_cpus_from_cpuinfo(&cpuinfo));
    (physical, logical as u32)
}

/// The number of distinct cores in the CPU topology.
fn physical_cpus(sys_root: &Path) -> Option<u32> {
    let cpus: Vec<PathBuf> = fs::read_dir(sys_root.join("devices/system/cpu"))
        .ok()?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .and_then(|name| name.strip_prefix("cpu"))
                .is_some_and(|rest| !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()))
        })
        .collect();
    for file in ["core_cpus_list", "thread_siblings_list"] {
        let cores: HashSet<String> = cpus
            .iter()
            .filter_map(|cpu| fs::read_to_string(cpu.join("topology").join(file)).ok())
            .filter(|text| text.lines().count() == 1)
            .map(|text| text.trim_end().to_string())
            .collect();
        if !cores.is_empty() {
            return Some(cores.len() as u32);
        }
    }
    None
}

/// The cores per physical package summed over the packages in cpuinfo.
fn physical_cpus_from_cpuinfo(cpuinfo: &str) -> u32 {
    let mut cores_by_package: HashMap<u32, u32> = HashMap::new();
    let mut package: HashMap<&str, u32> = HashMap::new();
    for line in cpuinfo.lines().chain([""]) {
        let line = line.trim();
        if line.is_empty() {
            if let (Some(&id), Some(&cores)) =
                (package.get("physical id"), package.get("cpu cores"))
            {
                cores_by_package.insert(id, cores);
            }
            package.clear();
            continue;
        }
        if let Some((key, value)) = line.split_once(':') {
            let key = key.trim();
            if (key == "physical id" || key == "cpu cores")
                && let Ok(value) = value.trim().parse()
            {
                package.insert(key, value);
            }
        }
    }
    cores_by_package.values().sum()
}

// ===== Network =====

fn network_counters(proc_root: &Path, sys_root: &Path) -> Vec<(String, f64)> {
    let mut counters = Vec::new();
    match net_dev(proc_root, sys_root) {
        Some((sent, recv)) => {
            counters.push(("network.sent".to_string(), sent as f64));
            counters.push(("network.recv".to_string(), recv as f64));
        }
        None => skip("network"),
    }
    match tcp_retransmits(proc_root) {
        Some(retransmits) => {
            counters.push(("network.tcpRetransmits".to_string(), retransmits as f64));
        }
        None => skip("network.tcpRetransmits"),
    }
    counters
}

/// Bytes sent and received over the interfaces that are not loopback and
/// not enslaved to a bond, bridge or team master.
fn net_dev(proc_root: &Path, sys_root: &Path) -> Option<(u64, u64)> {
    let text = fs::read_to_string(proc_root.join("net/dev")).ok()?;
    let (mut sent, mut recv) = (0, 0);
    for line in text.lines().skip(2) {
        let Some((name, stats)) = line.rsplit_once(':') else {
            continue;
        };
        let name = name.trim();
        let fields: Vec<&str> = stats.split_whitespace().collect();
        if name.is_empty() || fields.len() < 13 {
            continue;
        }
        let interface = sys_root.join("class/net").join(name);
        let loopback = fs::read_to_string(interface.join("flags"))
            .ok()
            .and_then(|flags| u64::from_str_radix(flags.trim().trim_start_matches("0x"), 16).ok())
            .is_some_and(|flags| flags & IFF_LOOPBACK != 0);
        if name == "lo" || loopback || interface.join("master").exists() {
            continue;
        }
        recv += fields[0].parse::<u64>().ok()?;
        sent += fields[8].parse::<u64>().ok()?;
    }
    Some((sent, recv))
}

/// The RetransSegs counter of the Tcp line of net/snmp.
fn tcp_retransmits(proc_root: &Path) -> Option<u64> {
    let text = fs::read_to_string(proc_root.join("net/snmp")).ok()?;
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

#[cfg(unix)]
fn disk_usage(path: &str) -> Option<DiskUsage> {
    let stat = nix::sys::statvfs::statvfs(path).ok()?;
    let block = stat.fragment_size() as u64;
    let blocks = stat.blocks() as u64;
    Some(DiskUsage {
        total: blocks * block,
        used: blocks.saturating_sub(stat.blocks_free() as u64) * block,
        free: stat.blocks_available() as u64 * block,
    })
}

#[cfg(not(unix))]
fn disk_usage(_path: &str) -> Option<DiskUsage> {
    None
}

/// Bytes read and written per device from diskstats.
fn diskstats(proc_root: &Path) -> Option<HashMap<String, (u64, u64)>> {
    let text = fs::read_to_string(proc_root.join("diskstats")).ok()?;
    let mut counters = HashMap::new();
    for line in text.lines() {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 14 || fields[3..14].iter().all(|field| *field == "0") {
            continue;
        }
        let (Ok(read), Ok(written)) = (fields[5].parse::<u64>(), fields[9].parse::<u64>()) else {
            continue;
        };
        counters.insert(
            fields[2].to_string(),
            (read * SECTOR_SIZE, written * SECTOR_SIZE),
        );
    }
    Some(counters)
}

/// The devices in `diskstats` whose file systems hold `paths`.
///
/// A device backs a path when its mount point is a prefix of the path. When
/// `/` is not among the mounted real file systems, as in a container whose
/// root is an overlay, every real device seen stands in for it. When no
/// device matches, every real device in `diskstats` is watched.
fn disk_devices(
    proc_root: &Path,
    sys_root: &Path,
    paths: &[String],
    diskstats: &HashMap<String, (u64, u64)>,
) -> Vec<String> {
    let partitions = partitions(proc_root, sys_root);
    let mut devices = HashSet::new();
    let mut root_missing = true;
    for partition in &partitions {
        if partition.mount_point == "/" {
            root_missing = false;
        }
        if paths
            .iter()
            .any(|path| path.starts_with(&partition.mount_point))
        {
            devices.insert(partition.device.clone());
        }
    }
    if root_missing && paths == ["/"] {
        devices.extend(
            partitions
                .iter()
                .map(|partition| &partition.device)
                .filter(|device| !pseudo_device(device))
                .cloned(),
        );
    }
    devices.retain(|device| diskstats.contains_key(device));
    if devices.is_empty() {
        devices.extend(
            diskstats
                .keys()
                .filter(|device| !pseudo_device(device))
                .cloned(),
        );
    }
    let mut devices: Vec<String> = devices.into_iter().collect();
    devices.sort();
    devices
}

fn pseudo_device(device: &str) -> bool {
    device.starts_with("loop") || device.starts_with("ram") || device.starts_with("zram")
}

struct Partition {
    /// The device name without its `/dev/` prefix.
    device: String,
    mount_point: String,
}

/// The mounted real file systems, from the mountinfo of pid 1 or of the
/// service itself, without bind mounts.
fn partitions(proc_root: &Path, sys_root: &Path) -> Vec<Partition> {
    let filesystems = real_filesystems(proc_root);
    let Some(text) = ["1", "self"]
        .iter()
        .find_map(|pid| fs::read_to_string(proc_root.join(pid).join("mountinfo")).ok())
    else {
        return Vec::new();
    };
    let mut first_device: HashMap<String, String> = HashMap::new();
    let mut partitions = Vec::new();
    for mount in parse_mountinfo(&text) {
        if !filesystems.contains(&mount.fstype) {
            continue;
        }
        let mut device = if mount.source.starts_with('/') || mount.root == "/" {
            mount.source.clone()
        } else {
            mount.root.clone()
        };
        if let Some(first) = first_device.get(&mount.device_id) {
            device = first.clone();
        }
        let subvolume = mount
            .super_opts
            .iter()
            .find_map(|opt| opt.strip_prefix("subvol="))
            .is_some_and(|subvol| subvol == mount.root);
        let bind = mount.source.starts_with('/') && mount.root != "/" && !subvolume;
        first_device
            .entry(mount.device_id.clone())
            .or_insert_with(|| device.clone());
        if bind {
            continue;
        }
        if device.starts_with("/dev/mapper/")
            && let Ok(real) = fs::canonicalize(&device)
        {
            device = real.to_string_lossy().into_owned();
        }
        if device == "/dev/root"
            && let Ok(link) = fs::read_link(sys_root.join("dev/block").join(&mount.device_id))
            && let Some(name) = link.file_name()
        {
            device = format!("/dev/{}", name.to_string_lossy());
        }
        partitions.push(Partition {
            device: device.trim_start_matches("/dev/").to_string(),
            mount_point: unescape(&mount.mount_point),
        });
    }
    partitions
}

/// The file system types backed by a device, plus zfs.
fn real_filesystems(proc_root: &Path) -> HashSet<String> {
    fs::read_to_string(proc_root.join("filesystems"))
        .unwrap_or_default()
        .lines()
        .filter_map(|line| match line.strip_prefix("nodev") {
            None => Some(line.trim().to_string()),
            Some(fstype) if fstype.trim() == "zfs" => Some("zfs".to_string()),
            Some(_) => None,
        })
        .collect()
}

/// Replaces the `\ooo` octal escapes the kernel writes in mount paths.
fn unescape(path: &str) -> String {
    let bytes = path.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'\\'
            && let Some(code) = path.get(i + 1..i + 4)
            && let Ok(byte) = u8::from_str_radix(code, 8)
        {
            out.push(byte);
            i += 4;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// One line of a mountinfo file.
struct Mount {
    device_id: String,
    root: String,
    mount_point: String,
    fstype: String,
    source: String,
    super_opts: Vec<String>,
}

fn parse_mountinfo(text: &str) -> Vec<Mount> {
    text.lines()
        .filter_map(|line| {
            let (mount, filesystem) = line.split_once(" - ")?;
            let mount: Vec<&str> = mount.split_whitespace().collect();
            let filesystem: Vec<&str> = filesystem.split_whitespace().collect();
            if mount.len() < 5 || filesystem.len() < 2 {
                return None;
            }
            Some(Mount {
                device_id: mount[2].to_string(),
                root: mount[3].to_string(),
                mount_point: mount[4].to_string(),
                fstype: filesystem[0].to_string(),
                source: filesystem[1].to_string(),
                super_opts: filesystem.get(2).map_or(Vec::new(), |opts| {
                    opts.split(',').map(str::to_string).collect()
                }),
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    const GIB_KB: u64 = 1024 * 1024;

    /// A fixture tree under a fresh temporary directory.
    struct Fixture(tempfile::TempDir);

    impl Fixture {
        fn new() -> Self {
            Self(tempfile::tempdir().unwrap())
        }

        fn write(&self, rel: &str, text: &str) {
            let path = self.0.path().join(rel);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        }

        /// A process with the given CPU ticks, threads and resident kB.
        fn process(&self, pid: u32, ticks: u64, threads: u64, rss_kb: u64, extra_status: &str) {
            self.write(
                &format!("{pid}/stat"),
                &format!(
                    "{pid} (python) S 0 {pid} {pid} 0 -1 4194560 0 0 0 0 {ticks} 0 0 0 20 0 {threads} 0 100 0 0"
                ),
            );
            self.write(
                &format!("{pid}/status"),
                &format!("Name:\tpython\nVmRSS:\t{rss_kb} kB\n{extra_status}"),
            );
        }

        fn cgroup2_mount(&self, pid: u32, root: &str) {
            self.write(
                &format!("{pid}/mountinfo"),
                &format!(
                    "1 0 0:1 {root} {} rw,relatime - cgroup2 cgroup rw\n",
                    self.0.path().join("sys/fs/cgroup").display()
                ),
            );
        }

        fn host(&self) -> Host {
            Host::new(self.0.path(), self.0.path().join("sys"))
        }
    }

    fn value(readings: &Readings, key: &str) -> Option<f64> {
        [&readings.metrics, &readings.averages, &readings.counters]
            .into_iter()
            .flatten()
            .find(|(k, _)| k == key)
            .map(|(_, v)| *v)
    }

    #[test]
    fn cgroup_limits_replace_the_host_denominators() {
        let fixture = Fixture::new();
        fixture.write(
            "meminfo",
            &format!(
                "MemTotal:       {} kB\nMemFree:        {} kB\nMemAvailable:   {} kB\n",
                16 * GIB_KB,
                GIB_KB,
                4 * GIB_KB
            ),
        );
        fixture.write("cpuinfo", &"processor\t: 0\n\n".repeat(4));
        for (cpu, cores) in [(0, "0,2"), (1, "1,3"), (2, "0,2"), (3, "1,3")] {
            fixture.write(
                &format!("sys/devices/system/cpu/cpu{cpu}/topology/core_cpus_list"),
                &format!("{cores}\n"),
            );
        }
        // pid 1: a container with memory and CPU quotas.
        fixture.process(1, 100, 4, 2 * GIB_KB, "Cpus_allowed_list:\t0-3\n");
        fixture.write("1/cgroup", "0::/kubepods/pod123/container456\n");
        fixture.cgroup2_mount(1, "/kubepods");
        let container = "sys/fs/cgroup/pod123/container456";
        fixture.write(
            &format!("{container}/memory.max"),
            &format!("{}\n", 8 * GIB_KB * 1024),
        );
        fixture.write(
            &format!("{container}/memory.current"),
            &format!("{}\n", 7 * GIB_KB * 1024),
        );
        fixture.write(&format!("{container}/cpu.max"), "400000 100000\n");
        fixture.write(
            &format!("{container}/cpu.stat"),
            "nr_periods 100\nnr_throttled 10\n",
        );
        fixture.write(&format!("{container}/memory.events"), "oom 1\noom_kill 1\n");
        // pid 2: pinned to two of the four CPUs, no quota.
        fixture.process(2, 100, 1, GIB_KB, "Cpus_allowed_list:\t0-1\n");
        fixture.write("2/cgroup", "0::/kubepods/pod2\n");
        fixture.cgroup2_mount(2, "/");
        fixture.write("sys/fs/cgroup/kubepods/pod2/cpu.max", "max 100000\n");

        let quota = Scope {
            pid: 1,
            ..Default::default()
        };
        let pinned = Scope {
            pid: 2,
            ..Default::default()
        };
        let no_cgroup = Scope {
            pid: 1,
            disable_cgroup: true,
            ..Default::default()
        };
        let scopes = [quota.clone(), pinned.clone(), no_cgroup.clone()];
        let host = fixture.host();
        let start = Instant::now();

        let first = host.sweep(&scopes, start);
        let readings = &first.scoped[&quota];
        assert_eq!(value(readings, "memory_percent"), Some(87.5));
        assert_eq!(value(readings, "proc.memory.availableMB"), Some(1024.0));
        assert_eq!(value(readings, "proc.memory.rssMB"), Some(2048.0));
        assert_eq!(value(readings, "proc.memory.percent"), Some(25.0));
        assert_eq!(value(readings, "proc.cpu.threads"), Some(4.0));
        assert_eq!(value(readings, "proc.memory.oomKills"), Some(1.0));
        assert_eq!(value(readings, "cpu"), None);
        assert_eq!(value(readings, "proc.cpu.throttledPercent"), None);

        fixture.process(1, 300, 4, 2 * GIB_KB, "Cpus_allowed_list:\t0-3\n");
        fixture.process(2, 200, 1, GIB_KB, "Cpus_allowed_list:\t0-1\n");
        fixture.write(
            &format!("{container}/cpu.stat"),
            "nr_periods 140\nnr_throttled 20\n",
        );
        fixture.write(&format!("{container}/memory.events"), "oom 3\noom_kill 3\n");
        let second = host.sweep(&scopes, start + Duration::from_secs(1));

        let readings = &second.scoped[&quota];
        assert_eq!(value(readings, "cpu"), Some(50.0));
        assert_eq!(value(readings, "proc.cpu.throttledPercent"), Some(25.0));
        assert_eq!(value(readings, "proc.memory.oomKills"), Some(3.0));

        let readings = &second.scoped[&pinned];
        assert_eq!(value(readings, "memory_percent"), Some(75.0));
        assert_eq!(value(readings, "proc.memory.availableMB"), Some(4096.0));
        assert_eq!(value(readings, "proc.memory.percent"), Some(6.25));
        assert_eq!(value(readings, "cpu"), Some(50.0));
        assert_eq!(value(readings, "proc.cpu.throttledPercent"), None);

        let readings = &second.scoped[&no_cgroup];
        assert_eq!(value(readings, "memory_percent"), Some(75.0));
        assert_eq!(value(readings, "cpu"), Some(100.0));
        assert_eq!(value(readings, "proc.memory.oomKills"), None);
    }

    #[test]
    fn process_trees_sum_their_members() {
        let fixture = Fixture::new();
        fixture.process(10, 100, 2, 1024, "");
        fixture.write("10/task/10/children", "11 12\n");
        fixture.process(11, 10, 1, 1024, "");
        fixture.process(12, 10, 1, 1024, "");
        fixture.write("12/task/12/children", "13\n");
        fixture.process(13, 10, 1, 1024, "");
        fixture.process(20, 50, 3, 2048, "");
        fixture.write("20/task/20/children", "21\n");
        fixture.process(21, 50, 1, 2048, "");

        let tree = Scope {
            pid: 10,
            track_process_tree: true,
            wandb_pids: vec![20],
            ..Default::default()
        };
        let alone = Scope {
            pid: 10,
            ..Default::default()
        };
        let scopes = [tree.clone(), alone.clone()];
        let host = fixture.host();
        let start = Instant::now();

        host.sweep(&scopes, start);
        for pid in [10, 11, 12, 13, 20, 21] {
            fixture.process(pid, 200, 1, 1024, "");
        }
        let sample = host.sweep(&scopes, start + Duration::from_secs(2));

        let readings = &sample.scoped[&tree];
        assert_eq!(value(readings, "proc.memory.rssMB"), Some(4.0));
        assert_eq!(value(readings, "proc.cpu.threads"), Some(4.0));
        assert_eq!(value(readings, "cpu"), Some(335.0));
        assert_eq!(value(readings, "wandb.memory.rssMB"), Some(2.0));
        assert_eq!(value(readings, "wandb.cpu"), Some(150.0));

        let readings = &sample.scoped[&alone];
        assert_eq!(value(readings, "proc.memory.rssMB"), Some(1.0));
        assert_eq!(value(readings, "cpu"), Some(50.0));
        assert_eq!(value(readings, "wandb.cpu"), None);
    }

    #[test]
    fn disk_devices_follow_the_mount_points() {
        let container = Fixture::new();
        container.write(
            "filesystems",
            "nodev\tsysfs\nnodev\toverlay\n\text4\n\tsquashfs\n",
        );
        container.write(
            "1/mountinfo",
            "30 1 0:40 / / rw - overlay overlay rw\n\
             31 30 8:1 / /boot rw - ext4 /dev/sda1 rw\n\
             32 30 7:0 / /snap/core rw - squashfs /dev/loop0 ro\n",
        );
        container.write(
            "diskstats",
            "8 1 sda1 100 0 2048 0 50 0 4096 0 0 0 0\n\
             7 0 loop0 10 0 512 0 0 0 0 0 0 0 0\n\
             259 0 nvme0n1 5 0 1024 0 5 0 1024 0 0 0 0\n",
        );
        let root = Scope {
            disk_paths: vec!["/".to_string()],
            ..Default::default()
        };
        let sample = container
            .host()
            .sweep(std::slice::from_ref(&root), Instant::now());
        let readings = &sample.scoped[&root];
        assert_eq!(value(readings, "disk.sda1.in"), Some(1.0));
        assert_eq!(value(readings, "disk.sda1.out"), Some(2.0));
        assert_eq!(value(readings, "disk.loop0.in"), None);
        assert_eq!(value(readings, "disk.nvme0n1.in"), None);

        let host = Fixture::new();
        host.write("filesystems", "\text4\n\txfs\n");
        host.write(
            "1/mountinfo",
            "20 1 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n\
             21 20 8:17 / /data rw - xfs /dev/sdb1 rw\n\
             22 20 8:33 / /mnt rw - ext4 /dev/sdc1 rw\n",
        );
        host.write(
            "diskstats",
            "259 2 nvme0n1p2 1 0 2048 0 1 0 2048 0 0 0 0\n\
             8 17 sdb1 1 0 4096 0 1 0 4096 0 0 0 0\n",
        );
        let data = Scope {
            disk_paths: vec!["/data".to_string()],
            ..Default::default()
        };
        let mnt = Scope {
            disk_paths: vec!["/mnt".to_string()],
            ..Default::default()
        };
        let sample = host
            .host()
            .sweep(&[data.clone(), mnt.clone()], Instant::now());
        let readings = &sample.scoped[&data];
        assert_eq!(value(readings, "disk.nvme0n1p2.in"), Some(1.0));
        assert_eq!(value(readings, "disk.sdb1.in"), Some(2.0));
        let readings = &sample.scoped[&mnt];
        assert_eq!(value(readings, "disk.nvme0n1p2.in"), Some(1.0));
        assert_eq!(value(readings, "disk.sdb1.in"), None);
        assert_eq!(value(readings, "disk.sdc1.in"), None);
    }

    #[test]
    fn network_skips_loopback_and_enslaved_interfaces() {
        let fixture = Fixture::new();
        fixture.write(
            "net/dev",
            "Inter-|   Receive                                                |  Transmit\n\
             \x20face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n\
             \x20   lo: 1000 10 0 0 0 0 0 0 1000 10 0 0 0 0 0 0\n\
             \x20 eth0: 5000 50 0 0 0 0 0 0 7000 70 0 0 0 0 0 0\n\
             \x20 eth1: 300 3 0 0 0 0 0 0 400 4 0 0 0 0 0 0\n\
             \x20bond0: 20 2 0 0 0 0 0 0 30 3 0 0 0 0 0 0\n",
        );
        fixture.write("sys/class/net/lo/flags", "0x9\n");
        fixture.write("sys/class/net/eth1/master", "");
        fixture.write(
            "net/snmp",
            "Ip: Forwarding DefaultTTL\nIp: 1 64\n\
             Tcp: RtoAlgorithm RtoMin RetransSegs OutRsts\nTcp: 1 200 42 7\n",
        );

        let sample = fixture.host().sweep(&[Scope::default()], Instant::now());
        let counters: HashMap<String, f64> = sample.counters.into_iter().collect();
        assert_eq!(counters["network.sent"], 7030.0);
        assert_eq!(counters["network.recv"], 5020.0);
        assert_eq!(counters["network.tcpRetransmits"], 42.0);
    }
}
