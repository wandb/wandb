//! Minimal protobuf wire-format decoding for the W&B `Record` message and the
//! sub-messages LEET consumes. Field numbers mirror `wandb_internal.proto`.

/// A single field in a protobuf message.
#[derive(Debug)]
pub enum Value<'a> {
    Varint(u64),
    Fixed64(u64),
    Fixed32(u32),
    Bytes(&'a [u8]),
}

impl<'a> Value<'a> {
    pub fn bytes(&self) -> &'a [u8] {
        match self {
            Value::Bytes(b) => b,
            _ => &[],
        }
    }

    pub fn string(&self) -> String {
        String::from_utf8_lossy(self.bytes()).into_owned()
    }

    pub fn varint(&self) -> u64 {
        match self {
            Value::Varint(v) => *v,
            Value::Fixed64(v) => *v,
            Value::Fixed32(v) => u64::from(*v),
            _ => 0,
        }
    }

    pub fn int64(&self) -> i64 {
        self.varint() as i64
    }
}

/// Iterates over (field_number, value) pairs of an encoded message.
pub struct Fields<'a> {
    buf: &'a [u8],
    pos: usize,
}

pub fn fields(buf: &[u8]) -> Fields<'_> {
    Fields { buf, pos: 0 }
}

impl<'a> Iterator for Fields<'a> {
    type Item = (u32, Value<'a>);

    fn next(&mut self) -> Option<Self::Item> {
        if self.pos >= self.buf.len() {
            return None;
        }
        let tag = self.read_varint()?;
        let field = (tag >> 3) as u32;
        let value = match tag & 7 {
            0 => Value::Varint(self.read_varint()?),
            1 => {
                let b = self.take(8)?;
                Value::Fixed64(u64::from_le_bytes(b.try_into().ok()?))
            }
            2 => {
                let len = self.read_varint()? as usize;
                Value::Bytes(self.take(len)?)
            }
            5 => {
                let b = self.take(4)?;
                Value::Fixed32(u32::from_le_bytes(b.try_into().ok()?))
            }
            _ => return None, // unsupported wire type: stop parsing
        };
        Some((field, value))
    }
}

impl<'a> Fields<'a> {
    fn read_varint(&mut self) -> Option<u64> {
        let mut out: u64 = 0;
        let mut shift = 0;
        loop {
            let b = *self.buf.get(self.pos)?;
            self.pos += 1;
            out |= u64::from(b & 0x7f) << shift;
            if b & 0x80 == 0 {
                return Some(out);
            }
            shift += 7;
            if shift >= 64 {
                return None;
            }
        }
    }

    fn take(&mut self, len: usize) -> Option<&'a [u8]> {
        let end = self.pos.checked_add(len)?;
        if end > self.buf.len() {
            return None;
        }
        let b = &self.buf[self.pos..end];
        self.pos = end;
        Some(b)
    }
}

// ---- Typed records ----

/// `google.protobuf.Timestamp`.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Timestamp {
    pub seconds: i64,
    pub nanos: i32,
}

impl Timestamp {
    fn parse(buf: &[u8]) -> Self {
        let mut t = Timestamp::default();
        for (f, v) in fields(buf) {
            match f {
                1 => t.seconds = v.int64(),
                2 => t.nanos = v.int64() as i32,
                _ => {}
            }
        }
        t
    }

    pub fn as_secs_f64(&self) -> f64 {
        self.seconds as f64 + f64::from(self.nanos) / 1e9
    }
}

/// Key + optional nested key + JSON-encoded value; shared shape between
/// HistoryItem, SummaryItem, and ConfigItem.
#[derive(Debug, Clone, Default)]
pub struct KeyedJsonItem {
    pub key: String,
    pub nested_key: Vec<String>,
    pub value_json: String,
}

impl KeyedJsonItem {
    fn parse(buf: &[u8]) -> Self {
        let mut item = KeyedJsonItem::default();
        for (f, v) in fields(buf) {
            match f {
                1 => item.key = v.string(),
                2 => item.nested_key.push(v.string()),
                16 => item.value_json = v.string(),
                _ => {}
            }
        }
        item
    }

    /// The item's key path (nested_key wins over key when present).
    pub fn path(&self) -> Vec<String> {
        if !self.nested_key.is_empty() {
            self.nested_key.clone()
        } else {
            vec![self.key.clone()]
        }
    }

    /// Dotted display key.
    pub fn dotted_key(&self) -> String {
        if !self.nested_key.is_empty() {
            self.nested_key.join(".")
        } else {
            self.key.clone()
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct HistoryRecord {
    pub items: Vec<KeyedJsonItem>,
    pub step: Option<i64>,
}

#[derive(Debug, Clone, Default)]
pub struct SummaryRecord {
    pub update: Vec<KeyedJsonItem>,
    pub remove: Vec<KeyedJsonItem>,
}

#[derive(Debug, Clone, Default)]
pub struct ConfigRecord {
    pub update: Vec<KeyedJsonItem>,
    pub remove: Vec<KeyedJsonItem>,
}

#[derive(Debug, Clone, Default)]
pub struct RunRecord {
    pub run_id: String,
    pub entity: String,
    pub project: String,
    pub config: Option<ConfigRecord>,
    pub summary: Option<SummaryRecord>,
    pub display_name: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub start_time: Option<Timestamp>,
}

#[derive(Debug, Clone, Default)]
pub struct StatsItem {
    pub key: String,
    pub value_json: String,
}

#[derive(Debug, Clone, Default)]
pub struct StatsRecord {
    pub timestamp: Option<Timestamp>,
    pub items: Vec<StatsItem>,
}

#[derive(Debug, Clone, Default)]
pub struct OutputRawRecord {
    /// 0 = stderr, 1 = stdout.
    pub output_type: u64,
    pub timestamp: Option<Timestamp>,
    pub line: String,
}

#[derive(Debug, Clone, Default)]
pub struct RunExitRecord {
    pub exit_code: i32,
}

#[derive(Debug, Clone, Default)]
pub struct GitRepoRecord {
    pub remote_url: String,
    pub commit: String,
}

#[derive(Debug, Clone, Default)]
pub struct DiskInfo {
    pub total: u64,
    pub used: u64,
}

#[derive(Debug, Clone, Default)]
pub struct AppleInfo {
    pub name: String,
    pub ecpu_cores: u32,
    pub pcpu_cores: u32,
    pub gpu_cores: u32,
    pub memory_gb: u32,
    pub swap_total_bytes: u64,
    pub ram_total_bytes: u64,
    pub mac_model: String,
}

#[derive(Debug, Clone, Default)]
pub struct GpuNvidiaInfo {
    pub name: String,
    pub memory_total: u64,
    pub cuda_cores: u32,
    pub architecture: String,
    pub uuid: String,
}

#[derive(Debug, Clone, Default)]
pub struct TrainiumInfo {
    pub name: String,
    pub vendor: String,
    pub neuron_device_count: u32,
    pub neuroncore_per_device_count: u32,
}

#[derive(Debug, Clone, Default)]
pub struct TpuInfo {
    pub name: String,
    pub hbm_gib: u32,
    pub devices_per_chip: u32,
    pub count: u32,
}

/// `EnvironmentRecord`: system metadata captured by a run writer.
#[derive(Debug, Clone, Default)]
pub struct EnvironmentRecord {
    pub os: String,
    pub python: String,
    pub started_at: Option<Timestamp>,
    pub docker: String,
    pub args: Vec<String>,
    pub program: String,
    pub code_path: String,
    pub code_path_local: String,
    pub git: Option<GitRepoRecord>,
    pub email: String,
    pub root: String,
    pub host: String,
    pub username: String,
    pub executable: String,
    pub colab: String,
    pub cpu_count: u32,
    pub cpu_count_logical: u32,
    pub gpu_type: String,
    pub gpu_count: u32,
    pub disk: Vec<(String, DiskInfo)>,
    pub memory_total: Option<u64>,
    pub cpu: Option<(u32, u32)>, // (count, count_logical)
    pub apple: Option<AppleInfo>,
    pub gpu_nvidia: Vec<GpuNvidiaInfo>,
    pub cuda_version: String,
    pub slurm: Vec<(String, String)>,
    pub trainium: Option<TrainiumInfo>,
    pub tpu: Option<TpuInfo>,
    pub writer_id: String,
}

/// The `Record` variants LEET consumes.
#[allow(clippy::large_enum_variant)] // Records are short-lived and few.
#[derive(Debug, Clone)]
pub enum RecordData {
    History(HistoryRecord),
    Summary(SummaryRecord),
    Config(ConfigRecord),
    Stats(StatsRecord),
    OutputRaw(OutputRawRecord),
    Run(RunRecord),
    Exit(RunExitRecord),
    Environment(EnvironmentRecord),
}

/// Decodes a top-level `Record`, returning `None` for variants LEET ignores.
pub fn parse_record(buf: &[u8]) -> Option<RecordData> {
    for (f, v) in fields(buf) {
        let data = match f {
            2 => RecordData::History(parse_history(v.bytes())),
            3 => RecordData::Summary(parse_summary(v.bytes())),
            5 => RecordData::Config(parse_config(v.bytes())),
            7 => RecordData::Stats(parse_stats(v.bytes())),
            13 => RecordData::OutputRaw(parse_output_raw(v.bytes())),
            17 => RecordData::Run(parse_run(v.bytes())),
            18 => RecordData::Exit(parse_exit(v.bytes())),
            26 => RecordData::Environment(parse_environment(v.bytes())),
            _ => continue,
        };
        return Some(data);
    }
    None
}

fn parse_history(buf: &[u8]) -> HistoryRecord {
    let mut rec = HistoryRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.items.push(KeyedJsonItem::parse(v.bytes())),
            2 => {
                for (sf, sv) in fields(v.bytes()) {
                    if sf == 1 {
                        rec.step = Some(sv.int64());
                    }
                }
            }
            _ => {}
        }
    }
    rec
}

fn parse_summary(buf: &[u8]) -> SummaryRecord {
    let mut rec = SummaryRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.update.push(KeyedJsonItem::parse(v.bytes())),
            2 => rec.remove.push(KeyedJsonItem::parse(v.bytes())),
            _ => {}
        }
    }
    rec
}

fn parse_config(buf: &[u8]) -> ConfigRecord {
    let mut rec = ConfigRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.update.push(KeyedJsonItem::parse(v.bytes())),
            2 => rec.remove.push(KeyedJsonItem::parse(v.bytes())),
            _ => {}
        }
    }
    rec
}

fn parse_run(buf: &[u8]) -> RunRecord {
    let mut rec = RunRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.run_id = v.string(),
            2 => rec.entity = v.string(),
            3 => rec.project = v.string(),
            4 => rec.config = Some(parse_config(v.bytes())),
            5 => rec.summary = Some(parse_summary(v.bytes())),
            8 => rec.display_name = v.string(),
            9 => rec.notes = v.string(),
            10 => rec.tags.push(v.string()),
            17 => rec.start_time = Some(Timestamp::parse(v.bytes())),
            _ => {}
        }
    }
    rec
}

fn parse_stats(buf: &[u8]) -> StatsRecord {
    let mut rec = StatsRecord::default();
    for (f, v) in fields(buf) {
        match f {
            2 => rec.timestamp = Some(Timestamp::parse(v.bytes())),
            3 => {
                let mut item = StatsItem::default();
                for (sf, sv) in fields(v.bytes()) {
                    match sf {
                        1 => item.key = sv.string(),
                        16 => item.value_json = sv.string(),
                        _ => {}
                    }
                }
                rec.items.push(item);
            }
            _ => {}
        }
    }
    rec
}

fn parse_output_raw(buf: &[u8]) -> OutputRawRecord {
    let mut rec = OutputRawRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.output_type = v.varint(),
            2 => rec.timestamp = Some(Timestamp::parse(v.bytes())),
            3 => rec.line = v.string(),
            _ => {}
        }
    }
    rec
}

fn parse_exit(buf: &[u8]) -> RunExitRecord {
    let mut rec = RunExitRecord::default();
    for (f, v) in fields(buf) {
        if f == 1 {
            rec.exit_code = v.int64() as i32;
        }
    }
    rec
}

fn parse_git(buf: &[u8]) -> GitRepoRecord {
    let mut rec = GitRepoRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.remote_url = v.string(),
            2 => rec.commit = v.string(),
            _ => {}
        }
    }
    rec
}

fn parse_environment(buf: &[u8]) -> EnvironmentRecord {
    let mut rec = EnvironmentRecord::default();
    for (f, v) in fields(buf) {
        match f {
            1 => rec.os = v.string(),
            2 => rec.python = v.string(),
            3 => rec.started_at = Some(Timestamp::parse(v.bytes())),
            4 => rec.docker = v.string(),
            5 => rec.args.push(v.string()),
            6 => rec.program = v.string(),
            7 => rec.code_path = v.string(),
            8 => rec.code_path_local = v.string(),
            9 => rec.git = Some(parse_git(v.bytes())),
            10 => rec.email = v.string(),
            11 => rec.root = v.string(),
            12 => rec.host = v.string(),
            13 => rec.username = v.string(),
            14 => rec.executable = v.string(),
            15 => rec.colab = v.string(),
            16 => rec.cpu_count = v.varint() as u32,
            17 => rec.cpu_count_logical = v.varint() as u32,
            18 => rec.gpu_type = v.string(),
            19 => rec.gpu_count = v.varint() as u32,
            20 => {
                // map<string, DiskInfo>
                let mut key = String::new();
                let mut info = DiskInfo::default();
                for (mf, mv) in fields(v.bytes()) {
                    match mf {
                        1 => key = mv.string(),
                        2 => {
                            for (df, dv) in fields(mv.bytes()) {
                                match df {
                                    1 => info.total = dv.varint(),
                                    2 => info.used = dv.varint(),
                                    _ => {}
                                }
                            }
                        }
                        _ => {}
                    }
                }
                rec.disk.push((key, info));
            }
            21 => {
                for (mf, mv) in fields(v.bytes()) {
                    if mf == 1 {
                        rec.memory_total = Some(mv.varint());
                    }
                }
            }
            22 => {
                let mut count = 0u32;
                let mut logical = 0u32;
                for (cf, cv) in fields(v.bytes()) {
                    match cf {
                        1 => count = cv.varint() as u32,
                        2 => logical = cv.varint() as u32,
                        _ => {}
                    }
                }
                rec.cpu = Some((count, logical));
            }
            23 => {
                let mut a = AppleInfo::default();
                for (af, av) in fields(v.bytes()) {
                    match af {
                        1 => a.name = av.string(),
                        2 => a.ecpu_cores = av.varint() as u32,
                        3 => a.pcpu_cores = av.varint() as u32,
                        4 => a.gpu_cores = av.varint() as u32,
                        5 => a.memory_gb = av.varint() as u32,
                        6 => a.swap_total_bytes = av.varint(),
                        7 => a.ram_total_bytes = av.varint(),
                        8 => a.mac_model = av.string(),
                        _ => {}
                    }
                }
                rec.apple = Some(a);
            }
            24 => {
                let mut g = GpuNvidiaInfo::default();
                for (gf, gv) in fields(v.bytes()) {
                    match gf {
                        1 => g.name = gv.string(),
                        2 => g.memory_total = gv.varint(),
                        3 => g.cuda_cores = gv.varint() as u32,
                        4 => g.architecture = gv.string(),
                        5 => g.uuid = gv.string(),
                        _ => {}
                    }
                }
                rec.gpu_nvidia.push(g);
            }
            25 => rec.cuda_version = v.string(),
            27 => {
                let mut key = String::new();
                let mut val = String::new();
                for (mf, mv) in fields(v.bytes()) {
                    match mf {
                        1 => key = mv.string(),
                        2 => val = mv.string(),
                        _ => {}
                    }
                }
                rec.slurm.push((key, val));
            }
            28 => {
                let mut t = TrainiumInfo::default();
                for (tf, tv) in fields(v.bytes()) {
                    match tf {
                        1 => t.name = tv.string(),
                        2 => t.vendor = tv.string(),
                        3 => t.neuron_device_count = tv.varint() as u32,
                        4 => t.neuroncore_per_device_count = tv.varint() as u32,
                        _ => {}
                    }
                }
                rec.trainium = Some(t);
            }
            29 => {
                let mut t = TpuInfo::default();
                for (tf, tv) in fields(v.bytes()) {
                    match tf {
                        1 => t.name = tv.string(),
                        2 => t.hbm_gib = tv.varint() as u32,
                        3 => t.devices_per_chip = tv.varint() as u32,
                        4 => t.count = tv.varint() as u32,
                        _ => {}
                    }
                }
                rec.tpu = Some(t);
            }
            199 => rec.writer_id = v.string(),
            _ => {}
        }
    }
    rec
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tag(field: u32, wire: u8) -> Vec<u8> {
        encode_varint(u64::from(field) << 3 | u64::from(wire))
    }

    fn encode_varint(mut v: u64) -> Vec<u8> {
        let mut out = Vec::new();
        loop {
            let b = (v & 0x7f) as u8;
            v >>= 7;
            if v == 0 {
                out.push(b);
                break;
            }
            out.push(b | 0x80);
        }
        out
    }

    fn bytes_field(field: u32, data: &[u8]) -> Vec<u8> {
        let mut out = tag(field, 2);
        out.extend(encode_varint(data.len() as u64));
        out.extend_from_slice(data);
        out
    }

    #[test]
    fn decodes_run_record() {
        let mut run = bytes_field(1, b"abc123");
        run.extend(bytes_field(3, b"proj"));
        run.extend(bytes_field(8, b"sunny-dawn-1"));
        run.extend(bytes_field(10, b"tag1"));
        run.extend(bytes_field(10, b"tag2"));

        let record = bytes_field(17, &run);
        match parse_record(&record) {
            Some(RecordData::Run(r)) => {
                assert_eq!(r.run_id, "abc123");
                assert_eq!(r.project, "proj");
                assert_eq!(r.display_name, "sunny-dawn-1");
                assert_eq!(r.tags, vec!["tag1", "tag2"]);
            }
            other => panic!("unexpected: {other:?}"),
        }
    }

    #[test]
    fn decodes_history_record() {
        let mut item = bytes_field(1, b"loss");
        item.extend(bytes_field(16, b"0.5"));
        let mut hist = bytes_field(1, &item);
        let mut step = tag(1, 0);
        step.extend(encode_varint(7));
        hist.extend(bytes_field(2, &step));

        let record = bytes_field(2, &hist);
        match parse_record(&record) {
            Some(RecordData::History(h)) => {
                assert_eq!(h.step, Some(7));
                assert_eq!(h.items.len(), 1);
                assert_eq!(h.items[0].key, "loss");
                assert_eq!(h.items[0].value_json, "0.5");
            }
            other => panic!("unexpected: {other:?}"),
        }
    }
}
