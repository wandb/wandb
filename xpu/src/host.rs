//! Host metrics: memory, CPU, disk and network for the machine and a
//! process tree, read with sysinfo on every platform, plus the cgroup v2
//! limits and TCP counters that only procfs has (Linux).
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
use crate::wandb_internal::{DiskInfo, EnvironmentRecord, GetMetadataRequest, MemoryInfo};

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
        system.refresh_cpu_list(CpuRefreshKind::nothing());
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

        system.refresh_memory_specifics(MemoryRefreshKind::nothing().with_ram());
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
        let total = system.total_memory();
        let available = system.available_memory();
        let children = children(system);

        let mut sample = Sample {
            counters: network_counters(networks),
            ..Default::default()
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

            let cgroup_memory = cgroup.and_then(|cgroup| {
                let limit = cgroup.memory_limit?;
                let current = read_u64(&cgroup.dir.join("memory.current"))?;
                Some((current, limit))
            });
            let denominator = match cgroup_memory {
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
                        if let Some(&(last_periods, last_throttled)) = cpu_stat.get(&path)
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
                        next_cpu_stat.insert(path, (periods, throttled));
                    }
                }
                if let Some(kills) = read_key_values(&cgroup.dir.join("memory.events"))
                    .and_then(|values| values.get("oom_kill").copied())
                {
                    readings.counter("proc.memory.oomKills", kills as f64);
                }
            }

            if scope.pid > 0 {
                readings.pids = descendants(&children, Pid::from_u32(scope.pid))
                    .into_iter()
                    .map(Pid::as_u32)
                    .collect();
                let tree = Tree::Process {
                    pid: scope.pid,
                    descendants: scope.track_process_tree,
                };
                let reading = trees
                    .entry(tree.clone())
                    .or_insert_with(|| read_tree(system, &tree.pids(&children)));
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
                        readings.average("cpu", capacity.map_or(reading.cpu, |c| reading.cpu / c));
                    }
                } else {
                    skip("process");
                }
            }

            if !scope.wandb_pids.is_empty() {
                let tree = Tree::Wandb(scope.wandb_pids.clone());
                let reading = trees
                    .entry(tree.clone())
                    .or_insert_with(|| read_tree(system, &tree.pids(&children)));
                readings.metric("wandb.memory.rssMB", reading.rss as f64 / MIB);
                if seen.contains(&tree) {
                    readings.average(
                        "wandb.cpu",
                        capacity.map_or(reading.cpu, |c| reading.cpu / c),
                    );
                }
            }

            let mut devices = BTreeMap::new();
            for path in &scope.disk_paths {
                match usage(disks, path) {
                    Some(usage) => {
                        readings.metric(format!("disk.{path}.usagePercent"), usage.used_percent());
                        readings.metric(format!("disk.{path}.usageGB"), usage.used as f64 / GIB);
                    }
                    None => skip("disk usage"),
                }
                if let Some(disk) = disk_for(disks, path) {
                    if cfg!(target_os = "linux")
                        && !disk.name().to_string_lossy().starts_with("/dev/")
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

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        EnvironmentRecord::default()
    }

    async fn probe(&self, request: &GetMetadataRequest, metadata: &mut EnvironmentRecord) {
        self.probe_host(&request.disk_paths, metadata);
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

/// The size and usage of the file system holding `path`.
#[cfg(target_os = "linux")]
fn usage(_disks: &Disks, path: &str) -> Option<DiskUsage> {
    let stat = nix::sys::statvfs::statvfs(path).ok()?;
    let block = stat.fragment_size() as u64;
    let blocks = stat.blocks() as u64;
    Some(DiskUsage {
        total: blocks * block,
        used: blocks.saturating_sub(stat.blocks_free() as u64) * block,
        free: stat.blocks_available() as u64 * block,
    })
}

#[cfg(not(target_os = "linux"))]
fn usage(disks: &Disks, path: &str) -> Option<DiskUsage> {
    let disk = disk_for(disks, path)?;
    let (total, free) = (disk.total_space(), disk.available_space());
    Some(DiskUsage {
        total,
        used: total.saturating_sub(free),
        free,
    })
}

/// The disk whose mount point is the longest prefix of `path`.
fn disk_for<'a>(disks: &'a Disks, path: &str) -> Option<&'a Disk> {
    let canonical = fs::canonicalize(path).ok()?;
    let canonical = canonical.to_str()?;
    // Windows canonical paths carry a verbatim prefix that mount points lack.
    let path = Path::new(canonical.strip_prefix(r"\\?\").unwrap_or(canonical));
    mount_for(
        path,
        disks.list().iter().map(|disk| (disk, disk.mount_point())),
    )
}

/// The item among `mounts` whose mount point is the longest prefix of `path`.
fn mount_for<'a, T>(path: &Path, mounts: impl Iterator<Item = (T, &'a Path)>) -> Option<T> {
    mounts
        .filter(|(_, mount)| path.starts_with(mount))
        .max_by_key(|(_, mount)| mount.as_os_str().len())
        .map(|(item, _)| item)
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
    fn mount_points_match_by_longest_prefix() {
        let mounts = [("root", "/"), ("data", "/data"), ("datafoo", "/datafoo")];
        let find = |path: &str| {
            mount_for(
                Path::new(path),
                mounts.iter().map(|(name, mount)| (*name, Path::new(mount))),
            )
        };
        assert_eq!(find("/data/x"), Some("data"));
        assert_eq!(find("/datafoo/x"), Some("datafoo"));
        assert_eq!(find("/data2"), Some("root"));
    }

    #[test]
    fn the_host_reports_its_own_process() {
        let host = Host::new();
        let scope = Scope {
            pid: std::process::id(),
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
    }
}
