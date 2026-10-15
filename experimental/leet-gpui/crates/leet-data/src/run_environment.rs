//! Port of `core/internal/runenvironment` — the subset used by
//! `core/internal/leet/runoverview.go` (`New`, `ProcessRecord`,
//! `ToRunConfigData`).
//!
//! Go implements `ToRunConfigData` by marshaling the record with
//! `protojson.MarshalOptions{Indent: "  "}` and re-parsing the text with
//! `encoding/json` into `map[string]any`. Here the same JSON object is built
//! directly (`environment_record_to_json`), following protojson's rules for
//! the fields of `EnvironmentRecord`:
//!
//! - field names are the descriptor JSON names (`json_name` options where
//!   present, lowerCamelCase otherwise — e.g. `cpu_count`, `gpu`,
//!   `startedAt`, `writerId`, and `Info` for `_info`);
//! - unpopulated implicit-presence fields are omitted (empty strings, zero
//!   ints, empty lists/maps, unset messages); present-but-empty messages
//!   are emitted as `{}`;
//! - uint32 → JSON number, uint64 → JSON string;
//! - `google.protobuf.Timestamp` → RFC 3339 string in UTC with 0/3/6/9
//!   fractional digits, and marshaling FAILS for out-of-range timestamps —
//!   in which case Go's `ToRunConfigData` returns nil, dropping all
//!   environment data (quirk preserved).
//
// PARITY: Go re-parses the JSON text, so all numbers become float64 and map
// order is lost; building serde_json Values directly is equivalent because
// uint32 fields are stored as f64-backed Numbers (see put_u32) so they
// render like Go's float64s, uint64 fields are strings per protojson in
// both, and serde_json maps iterate sorted.

use leet_proto::prost::Message;
use leet_proto::wandb_internal::{
    AppleInfo, CoreWeaveInfo, CpuInfo, DiskInfo, EnvironmentRecord, GitRepoRecord, GpuAmdInfo,
    GpuNvidiaInfo, MemoryInfo, RecordInfo, TpuInfo, TrainiumInfo,
};
use serde_json::{Map, Value};

/// RunEnvironment stores the information about the system, hardware,
/// software, and execution parameters for a run's writer.
// PARITY: Go guards this with a sync.Mutex; dropped — model-side state is
// accessed from the single update/view thread (docs/CONCURRENCY.md).
#[derive(Debug)]
pub struct RunEnvironment {
    /// Unique ID of the writer to the run.
    writer_id: String,

    environment: EnvironmentRecord,
}

impl RunEnvironment {
    pub fn new(writer_id: String) -> Self {
        RunEnvironment {
            writer_id,
            environment: EnvironmentRecord::default(),
        }
    }

    pub fn process_record(&mut self, environment: &EnvironmentRecord) {
        // PARITY: Go uses proto.Merge(dst, src). prost has no
        // message-to-message merge, but re-decoding src's wire bytes into
        // dst is identical: set implicit-presence scalars overwrite,
        // repeated fields append, map entries replace per key, and nested
        // messages merge recursively.
        let bytes = environment.encode_to_vec();
        self.environment
            .merge(bytes.as_slice())
            .expect("re-decoding just-encoded bytes cannot fail");
    }

    /// ToRunConfigData returns the data to store in the "e" field of the run
    /// config.
    ///
    /// Environment info in the config is stored per unique writer ID to
    /// support multi-writer use cases (e.g. shared mode or resume).
    // PARITY: returns None where Go returns a nil map — on a marshal error
    // (invalid timestamp) or when the record is all-default.
    pub fn to_run_config_data(&self) -> Option<Map<String, Value>> {
        let Ok(m) = environment_record_to_json(&self.environment) else {
            return None;
        };

        if m.is_empty() {
            return None;
        }

        let mut data = Map::new();
        data.insert(self.writer_id.clone(), Value::Object(m));
        Some(data)
    }
}

/// protojson would refuse to marshal the record (invalid timestamp).
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("invalid value for Timestamp")]
struct InvalidTimestamp;

/// Seconds of 0001-01-01T00:00:00Z — protojson's minimum Timestamp.
const MIN_TIMESTAMP_SECONDS: i64 = -62_135_596_800;
/// Seconds of 9999-12-31T23:59:59Z — protojson's maximum Timestamp.
const MAX_TIMESTAMP_SECONDS: i64 = 253_402_300_799;

fn environment_record_to_json(
    rec: &EnvironmentRecord,
) -> Result<Map<String, Value>, InvalidTimestamp> {
    let mut m = Map::new();
    put_string(&mut m, "os", &rec.os);
    put_string(&mut m, "python", &rec.python);
    if let Some(ts) = &rec.started_at {
        if !(MIN_TIMESTAMP_SECONDS..=MAX_TIMESTAMP_SECONDS).contains(&ts.seconds)
            || !(0..=999_999_999).contains(&ts.nanos)
        {
            return Err(InvalidTimestamp);
        }
        // PARITY: prost-types' Display prints exactly protojson's Timestamp
        // form for in-range values: RFC 3339, UTC "Z", fractional seconds
        // in 0/3/6/9 digits.
        m.insert("startedAt".to_string(), Value::String(ts.to_string()));
    }
    put_string(&mut m, "docker", &rec.docker);
    if !rec.args.is_empty() {
        m.insert(
            "args".to_string(),
            Value::Array(rec.args.iter().map(|s| Value::String(s.clone())).collect()),
        );
    }
    put_string(&mut m, "program", &rec.program);
    put_string(&mut m, "codePath", &rec.code_path);
    put_string(&mut m, "codePathLocal", &rec.code_path_local);
    if let Some(git) = &rec.git {
        m.insert(
            "git".to_string(),
            Value::Object(git_repo_record_to_json(git)),
        );
    }
    put_string(&mut m, "email", &rec.email);
    put_string(&mut m, "root", &rec.root);
    put_string(&mut m, "host", &rec.host);
    put_string(&mut m, "username", &rec.username);
    put_string(&mut m, "executable", &rec.executable);
    put_string(&mut m, "colab", &rec.colab);
    put_u32(&mut m, "cpu_count", rec.cpu_count);
    put_u32(&mut m, "cpu_count_logical", rec.cpu_count_logical);
    put_string(&mut m, "gpu", &rec.gpu_type);
    put_u32(&mut m, "gpu_count", rec.gpu_count);
    if !rec.disk.is_empty() {
        let mut disk = Map::new();
        for (key, info) in &rec.disk {
            disk.insert(key.clone(), Value::Object(disk_info_to_json(info)));
        }
        m.insert("disk".to_string(), Value::Object(disk));
    }
    if let Some(memory) = &rec.memory {
        m.insert(
            "memory".to_string(),
            Value::Object(memory_info_to_json(memory)),
        );
    }
    if let Some(cpu) = &rec.cpu {
        m.insert("cpu".to_string(), Value::Object(cpu_info_to_json(cpu)));
    }
    if let Some(apple) = &rec.apple {
        m.insert(
            "apple".to_string(),
            Value::Object(apple_info_to_json(apple)),
        );
    }
    if !rec.gpu_nvidia.is_empty() {
        m.insert(
            "gpu_nvidia".to_string(),
            Value::Array(
                rec.gpu_nvidia
                    .iter()
                    .map(|g| Value::Object(gpu_nvidia_info_to_json(g)))
                    .collect(),
            ),
        );
    }
    put_string(&mut m, "cudaVersion", &rec.cuda_version);
    if !rec.gpu_amd.is_empty() {
        m.insert(
            "gpu_amd".to_string(),
            Value::Array(
                rec.gpu_amd
                    .iter()
                    .map(|g| Value::Object(gpu_amd_info_to_json(g)))
                    .collect(),
            ),
        );
    }
    if !rec.slurm.is_empty() {
        let mut slurm = Map::new();
        for (key, value) in &rec.slurm {
            slurm.insert(key.clone(), Value::String(value.clone()));
        }
        m.insert("slurm".to_string(), Value::Object(slurm));
    }
    if let Some(trainium) = &rec.trainium {
        m.insert(
            "trainium".to_string(),
            Value::Object(trainium_info_to_json(trainium)),
        );
    }
    if let Some(tpu) = &rec.tpu {
        m.insert("tpu".to_string(), Value::Object(tpu_info_to_json(tpu)));
    }
    if let Some(coreweave) = &rec.coreweave {
        m.insert(
            "coreweave".to_string(),
            Value::Object(core_weave_info_to_json(coreweave)),
        );
    }
    put_string(&mut m, "writerId", &rec.writer_id);
    if let Some(info) = &rec.info {
        m.insert("Info".to_string(), Value::Object(record_info_to_json(info)));
    }
    Ok(m)
}

fn git_repo_record_to_json(rec: &GitRepoRecord) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "remote", &rec.remote_url);
    put_string(&mut m, "commit", &rec.commit);
    m
}

fn disk_info_to_json(rec: &DiskInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_u64(&mut m, "total", rec.total);
    put_u64(&mut m, "used", rec.used);
    m
}

fn memory_info_to_json(rec: &MemoryInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_u64(&mut m, "total", rec.total);
    m
}

fn cpu_info_to_json(rec: &CpuInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_u32(&mut m, "count", rec.count);
    put_u32(&mut m, "countLogical", rec.count_logical);
    m
}

fn apple_info_to_json(rec: &AppleInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "name", &rec.name);
    put_u32(&mut m, "ecpuCores", rec.ecpu_cores);
    put_u32(&mut m, "pcpuCores", rec.pcpu_cores);
    put_u32(&mut m, "gpuCores", rec.gpu_cores);
    put_u32(&mut m, "memoryGb", rec.memory_gb);
    put_u64(&mut m, "swapTotalBytes", rec.swap_total_bytes);
    put_u64(&mut m, "ramTotalBytes", rec.ram_total_bytes);
    put_string(&mut m, "macModel", &rec.mac_model);
    m
}

fn gpu_nvidia_info_to_json(rec: &GpuNvidiaInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "name", &rec.name);
    put_u64(&mut m, "memoryTotal", rec.memory_total);
    put_u32(&mut m, "cudaCores", rec.cuda_cores);
    put_string(&mut m, "architecture", &rec.architecture);
    put_string(&mut m, "uuid", &rec.uuid);
    m
}

fn gpu_amd_info_to_json(rec: &GpuAmdInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "id", &rec.id);
    put_string(&mut m, "uniqueId", &rec.unique_id);
    put_string(&mut m, "vbiosVersion", &rec.vbios_version);
    put_string(&mut m, "performanceLevel", &rec.performance_level);
    put_string(&mut m, "gpuOverdrive", &rec.gpu_overdrive);
    put_string(&mut m, "gpuMemoryOverdrive", &rec.gpu_memory_overdrive);
    put_string(&mut m, "maxPower", &rec.max_power);
    put_string(&mut m, "series", &rec.series);
    put_string(&mut m, "model", &rec.model);
    put_string(&mut m, "vendor", &rec.vendor);
    put_string(&mut m, "sku", &rec.sku);
    put_string(&mut m, "sclkRange", &rec.sclk_range);
    put_string(&mut m, "mclkRange", &rec.mclk_range);
    m
}

fn trainium_info_to_json(rec: &TrainiumInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "name", &rec.name);
    put_string(&mut m, "vendor", &rec.vendor);
    put_u32(&mut m, "neuronDeviceCount", rec.neuron_device_count);
    put_u32(
        &mut m,
        "neuroncorePerDeviceCount",
        rec.neuroncore_per_device_count,
    );
    m
}

fn tpu_info_to_json(rec: &TpuInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "name", &rec.name);
    put_u32(&mut m, "hbmGib", rec.hbm_gib);
    put_u32(&mut m, "devicesPerChip", rec.devices_per_chip);
    put_u32(&mut m, "count", rec.count);
    m
}

fn core_weave_info_to_json(rec: &CoreWeaveInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "clusterName", &rec.cluster_name);
    put_string(&mut m, "orgId", &rec.org_id);
    put_string(&mut m, "region", &rec.region);
    m
}

fn record_info_to_json(rec: &RecordInfo) -> Map<String, Value> {
    let mut m = Map::new();
    put_string(&mut m, "streamId", &rec.stream_id);
    put_string(&mut m, "TracelogId", &rec.tracelog_id);
    m
}

fn put_string(m: &mut Map<String, Value>, key: &str, value: &str) {
    if !value.is_empty() {
        m.insert(key.to_string(), Value::String(value.to_string()));
    }
}

// PARITY: Go's ToRunConfigData re-parses the protojson text with
// encoding/json, so uint32 fields surface as float64 and fmt.Sprint renders
// them with %g — scientific at decimal exponent >= 6 (e.g.
// cpu_count_logical=2000000 is "2e+06", not "2000000"). Stored as an
// f64-backed Number so go_sprint takes the float path.
fn put_u32(m: &mut Map<String, Value>, key: &str, value: u32) {
    if value != 0 {
        let n = serde_json::Number::from_f64(f64::from(value)).expect("u32 is finite");
        m.insert(key.to_string(), Value::Number(n));
    }
}

/// protojson emits uint64 values as JSON strings.
fn put_u64(m: &mut Map<String, Value>, key: &str, value: u64) {
    if value != 0 {
        m.insert(key.to_string(), Value::String(value.to_string()));
    }
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;
    use serde_json::json;

    use super::*;

    // The Go package has no test file; these anchor the used-subset
    // behavior (protojson field naming/omission, proto.Merge semantics,
    // and the nil returns of ToRunConfigData).

    #[test]
    fn to_run_config_data_keys_by_writer_id() {
        let mut env = RunEnvironment::new("writer-1".to_string());
        env.process_record(&EnvironmentRecord {
            writer_id: "writer-1".to_string(),
            os: "linux".to_string(),
            cpu_count: 8,
            memory: Some(MemoryInfo { total: 1024 }),
            git: Some(GitRepoRecord::default()),
            ..Default::default()
        });

        let data = env.to_run_config_data().expect("expected data");
        assert_eq!(
            Value::Object(data),
            json!({
                "writer-1": {
                    "os": "linux",
                    // uint32 fields are float64 after Go's encoding/json
                    // re-parse; float-tagged here too (see put_u32).
                    "cpu_count": 8.0,
                    // uint64 fields are strings, per protojson.
                    "memory": {"total": "1024"},
                    // A present-but-empty message marshals as {}.
                    "git": {},
                    "writerId": "writer-1",
                },
            }),
        );
    }

    #[test]
    fn to_run_config_data_empty_record_is_none() {
        let env = RunEnvironment::new("writer-1".to_string());
        assert_eq!(env.to_run_config_data(), None);
    }

    #[test]
    fn to_run_config_data_invalid_timestamp_drops_everything() {
        // PARITY: protojson refuses out-of-range timestamps, and Go's
        // ToRunConfigData turns that error into a nil map.
        let mut env = RunEnvironment::new("w".to_string());
        env.environment.os = "linux".to_string();
        set_started_at(&mut env.environment, 0, 0);
        // A valid epoch timestamp marshals fine...
        assert!(env.to_run_config_data().is_some());
        // ...but an out-of-range one poisons the whole record.
        set_started_at(&mut env.environment, MAX_TIMESTAMP_SECONDS + 1, 0);
        assert_eq!(env.to_run_config_data(), None);
    }

    #[test]
    fn process_record_merges() {
        let mut env = RunEnvironment::new("w".to_string());
        env.process_record(&EnvironmentRecord {
            os: "linux".to_string(),
            args: vec!["--a".to_string()],
            ..Default::default()
        });
        env.process_record(&EnvironmentRecord {
            os: "darwin".to_string(),
            python: "3.11.8".to_string(),
            args: vec!["--b".to_string()],
            ..Default::default()
        });

        // Set scalars overwrite, unset ones are preserved, repeated append.
        assert_eq!(env.environment.os, "darwin");
        assert_eq!(env.environment.python, "3.11.8");
        assert_eq!(
            env.environment.args,
            vec!["--a".to_string(), "--b".to_string()]
        );
    }

    #[test]
    fn timestamp_formats_like_protojson() {
        let mut env = RunEnvironment::new("w".to_string());
        set_started_at(&mut env.environment, 1_709_286_896, 123_000_000);
        let data = env.to_run_config_data().expect("expected data");
        let started_at = &data["w"]["startedAt"];
        assert_eq!(started_at, &json!("2024-03-01T09:54:56.123Z"));
    }

    /// Sets `started_at` without naming the foreign prost-types Timestamp
    /// type (leet-data has no prost-types dependency).
    fn set_started_at(rec: &mut EnvironmentRecord, seconds: i64, nanos: i32) {
        rec.started_at = Some(Default::default());
        if let Some(ts) = &mut rec.started_at {
            ts.seconds = seconds;
            ts.nanos = nanos;
        }
    }
}
