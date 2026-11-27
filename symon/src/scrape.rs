//! OpenMetrics and DCGM exporter endpoints, scraped over HTTP.
//!
//! One scrape per sweep serves every subscriber that asked for an endpoint,
//! and the label sets of a metric are numbered once per endpoint, so every
//! subscriber sees the same `openmetrics.<endpoint>.<metric>.<index>` keys.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Mutex;
use std::time::Duration;

use log::{debug, warn};
use regex_lite::Regex;
use reqwest::{Client, IntoUrl, Url};
use serde::Deserialize;

use crate::metrics::{self, Filter, Sample, Scope};
use crate::monitors::Collector;
use crate::wandb_internal::{EnvironmentRecord, GetMetadataRequest, GpuNvidiaInfo};

const TIMEOUT: Duration = Duration::from_secs(5);

type Headers = BTreeMap<String, String>;
type LabelSet = BTreeMap<String, String>;

/// An OpenMetrics endpoint as a subscriber configured it.
#[derive(Clone, PartialEq, Eq, Hash)]
struct Endpoint {
    name: String,
    url: String,
    headers: Headers,
    filters: Vec<Filter>,
}

/// A metric regex and the label regexes that must all match.
type CompiledFilter = (Regex, Vec<(String, Regex)>);

/// What the scrapes of an endpoint share: its compiled filters and the
/// index of every label set seen so far, by metric.
struct EndpointState {
    /// A filter that does not compile is kept as None and never matches,
    /// as in wandb-core, so a typo does not let every metric through.
    filters: Vec<Option<CompiledFilter>>,
    indexes: HashMap<String, HashMap<LabelSet, usize>>,
}

impl EndpointState {
    fn new(filters: &[Filter]) -> Self {
        let compile = |filter: &Filter| {
            let metric = Regex::new(&filter.metric_regex)?;
            let labels = filter
                .label_regexes
                .iter()
                .map(|(label, regex)| Ok((label.clone(), Regex::new(regex)?)))
                .collect::<Result<Vec<_>, regex_lite::Error>>()?;
            Ok::<_, regex_lite::Error>((metric, labels))
        };
        let filters = filters
            .iter()
            .map(|filter| {
                compile(filter)
                    .map_err(|e| warn!("OpenMetrics filter {filter:?} matches nothing: {e}"))
                    .ok()
            })
            .collect();
        Self {
            filters,
            indexes: HashMap::new(),
        }
    }

    /// Whether a sample passes the filters: any filter whose metric regex
    /// matches `<name>.<metric>` and whose label regexes all match.
    fn keep(&self, name: &str, metric: &str, labels: &HashMap<String, String>) -> bool {
        if self.filters.is_empty() {
            return true;
        }
        let full_name = format!("{name}.{metric}");
        self.filters
            .iter()
            .flatten()
            .any(|(metric_regex, label_regexes)| {
                metric_regex.is_match(&full_name)
                    && label_regexes.iter().all(|(label, regex)| {
                        labels.get(label).is_some_and(|value| regex.is_match(value))
                    })
            })
    }

    /// The gauges and counters in one scrape of endpoint `name`, keyed
    /// `openmetrics.<name>.<metric>.<index>`.
    fn metrics(&mut self, name: &str, text: &str) -> Vec<(String, f64)> {
        let mut metrics = Vec::new();
        for (metric, labels, value) in parse(text) {
            if !self.keep(name, &metric, &labels) {
                continue;
            }
            let labels: LabelSet = labels.into_iter().collect();
            let indexes = self.indexes.entry(metric.clone()).or_default();
            let next = indexes.len();
            let index = *indexes.entry(labels).or_insert(next);
            metrics.push((format!("openmetrics.{name}.{metric}.{index}"), value));
        }
        metrics
    }
}

/// The gauge and counter samples of a Prometheus text exposition, as
/// (metric, labels, value). Samples of other or unknown types are skipped.
fn parse(text: &str) -> Vec<(String, HashMap<String, String>, f64)> {
    let mut types: HashMap<&str, &str> = HashMap::new();
    let mut samples = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("# TYPE ") {
            if let Some((metric, kind)) = rest.trim().split_once(char::is_whitespace) {
                types.insert(metric, kind.trim());
            }
            continue;
        }
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((metric, labels, rest)) = split_sample(line) else {
            continue;
        };
        if !matches!(types.get(metric), Some(&"gauge" | &"counter")) {
            continue;
        }
        let Some(Ok(value)) = rest.split_whitespace().next().map(str::parse::<f64>) else {
            continue;
        };
        samples.push((metric.to_string(), labels, value));
    }
    samples
}

/// Splits `metric{labels} value [timestamp]` into its parts.
fn split_sample(line: &str) -> Option<(&str, HashMap<String, String>, &str)> {
    match line.find('{') {
        Some(open) => {
            let close = line.rfind('}')?;
            let labels = parse_labels(line.get(open + 1..close)?)?;
            Some((&line[..open], labels, &line[close + 1..]))
        }
        None => {
            let (metric, rest) = line.split_once(char::is_whitespace)?;
            Some((metric, HashMap::new(), rest))
        }
    }
}

/// Parses `name="value",...`, where a value may contain commas and the
/// escapes `\"`, `\\` and `\n`.
fn parse_labels(text: &str) -> Option<HashMap<String, String>> {
    let mut labels = HashMap::new();
    let mut rest = text.trim_start_matches([',', ' ']);
    while !rest.is_empty() {
        let (name, after) = rest.split_once('=')?;
        let quoted = after.strip_prefix('"')?;
        let mut chars = quoted.char_indices();
        let mut value = String::new();
        let end = loop {
            match chars.next()? {
                (i, '"') => break i,
                (_, '\\') => value.push(match chars.next()?.1 {
                    'n' => '\n',
                    c => c,
                }),
                (_, c) => value.push(c),
            }
        };
        labels.insert(name.trim().to_string(), value);
        rest = quoted[end + 1..].trim_start_matches([',', ' ']);
    }
    Some(labels)
}

/// The base URL and PromQL queries of a Prometheus instant-query URL such
/// as `http://gateway:9400/api/v1/query?query=DCGM_FI_DEV_GPU_TEMP`.
fn parse_promql_url(url: &str) -> Result<(String, Vec<String>), String> {
    let url = Url::parse(url).map_err(|e| e.to_string())?;
    let host = url.host_str().ok_or("no host")?;
    let base = match url.port() {
        Some(port) => format!("{}://{host}:{port}", url.scheme()),
        None => format!("{}://{host}", url.scheme()),
    };
    let queries: Vec<String> = url
        .query_pairs()
        .filter(|(key, _)| key == "query")
        .map(|(_, query)| query.into_owned())
        .collect();
    if queries.is_empty() {
        return Err("no query parameter provided".to_string());
    }
    Ok((base, queries))
}

#[derive(Deserialize)]
struct PromResponse {
    status: String,
    #[serde(default)]
    data: PromData,
    #[serde(default, rename = "errorType")]
    error_type: String,
    #[serde(default)]
    error: String,
}

#[derive(Deserialize, Default)]
struct PromData {
    #[serde(default, rename = "resultType")]
    result_type: String,
    #[serde(default)]
    result: Vec<PromSample>,
}

/// One element of an instant query's vector: its labels and the sample's
/// timestamp and value, the value encoded as a string.
#[derive(Deserialize)]
struct PromSample {
    metric: BTreeMap<String, String>,
    value: (f64, String),
}

/// A DCGM exporter sample about one GPU.
struct GpuSample {
    name: String,
    value: f64,
    index: String,
    uuid: String,
    model_name: String,
    /// The node, or else the hostname, the GPU is in.
    label: String,
}

impl GpuSample {
    /// Parses a sample, or None without a GPU index or a numeric value.
    fn parse(sample: PromSample) -> Option<Self> {
        let get = |label: &str| sample.metric.get(label).cloned().unwrap_or_default();
        let device = get("device");
        let mut index = get("gpu");
        if index.is_empty() {
            index = device.strip_prefix("nvidia").unwrap_or(&device).to_string();
        }
        if index.is_empty() {
            return None;
        }
        let node = get("node");
        Some(Self {
            name: get("__name__"),
            value: sample.value.1.parse().ok()?,
            index,
            uuid: get("uuid"),
            model_name: get("modelName"),
            label: if node.is_empty() {
                get("hostname")
            } else {
                node
            },
        })
    }

    /// The `gpu.<index>.<metric>[/l:<label>]` key of a DCGM field W&B
    /// charts, or None for other fields.
    fn key(&self) -> Option<String> {
        let metric = match self.name.as_str() {
            "DCGM_FI_DEV_GPU_TEMP" => "temp",
            "DCGM_FI_DEV_POWER_USAGE" => "powerWatts",
            "DCGM_FI_DEV_GPU_UTIL" => "gpu",
            "DCGM_FI_DEV_MEM_COPY_UTIL" => "memory",
            "DCGM_FI_DEV_SM_CLOCK" => "smClock",
            "DCGM_FI_DEV_FB_USED" => "memoryUsed",
            "DCGM_FI_DEV_FB_TOTAL" => "memoryTotal",
            "DCGM_FI_PROF_PCIE_TX_BYTES" => "pcieTxBytes",
            "DCGM_FI_PROF_PCIE_RX_BYTES" => "pcieRxBytes",
            "DCGM_FI_PROF_NVLINK_TX_BYTES" => "nvlinkTxBytes",
            "DCGM_FI_PROF_NVLINK_RX_BYTES" => "nvlinkRxBytes",
            "DCGM_FI_DEV_MEMORY_TEMP" => "memoryTemp",
            "DCGM_FI_DEV_GPU_MAX_OP_TEMP" => "maxOpTemp",
            "DCGM_FI_DEV_MEM_MAX_OP_TEMP" => "memoryMaxOpTemp",
            "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION" => "totalEnergyConsumption",
            "DCGM_FI_PROF_SM_ACTIVE" => "smActive",
            "DCGM_FI_PROF_SM_OCCUPANCY" => "smOccupancy",
            "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE" => "pipeTensorActive",
            "DCGM_FI_PROF_PIPE_FP64_ACTIVE" => "pipeFp64Active",
            "DCGM_FI_PROF_PIPE_FP32_ACTIVE" => "pipeFp32Active",
            "DCGM_FI_PROF_PIPE_FP16_ACTIVE" => "pipeFp16Active",
            "DCGM_FI_DEV_FB_FREE" => "memoryFree",
            _ => return None,
        };
        let key = format!("gpu.{}.{metric}", self.index);
        Some(if self.label.is_empty() {
            key
        } else {
            format!("{key}/l:{}", self.label)
        })
    }
}

async fn request(
    client: &Client,
    url: impl IntoUrl,
    headers: &Headers,
) -> Result<reqwest::Response, String> {
    let mut request = client.get(url);
    for (name, value) in headers {
        request = request.header(name.as_str(), value.as_str());
    }
    request
        .send()
        .await
        .and_then(|response| response.error_for_status())
        .map_err(|e| e.to_string())
}

/// The GPU samples of every query of a DCGM exporter URL.
async fn query_dcgm(
    client: &Client,
    exporter: &str,
    headers: &Headers,
) -> Result<Vec<GpuSample>, String> {
    let (base, queries) = parse_promql_url(exporter)?;
    let mut samples = Vec::new();
    for query in queries {
        let url = Url::parse_with_params(&format!("{base}/api/v1/query"), [("query", &query)])
            .map_err(|e| e.to_string())?;
        let response: PromResponse = request(client, url, headers)
            .await?
            .json()
            .await
            .map_err(|e| e.to_string())?;
        if response.status != "success" {
            return Err(format!("{}: {}", response.error_type, response.error));
        }
        if response.data.result_type != "vector" {
            return Err(format!(
                "unexpected result type {:?}",
                response.data.result_type
            ));
        }
        samples.extend(
            response
                .data
                .result
                .into_iter()
                .filter_map(GpuSample::parse),
        );
    }
    Ok(samples)
}

/// Groups the scopes by the endpoints `of` reads from them, in order of
/// first appearance.
fn group_by<K: PartialEq>(
    scopes: &[Scope],
    of: impl Fn(&Scope) -> Vec<K>,
) -> Vec<(K, Vec<&Scope>)> {
    let mut groups: Vec<(K, Vec<&Scope>)> = Vec::new();
    for scope in scopes {
        for key in of(scope) {
            match groups.iter_mut().find(|(k, _)| *k == key) {
                Some((_, scopes)) => scopes.push(scope),
                None => groups.push((key, vec![scope])),
            }
        }
    }
    groups
}

pub struct Scraper {
    client: Client,
    /// The state of every endpoint ever asked for; a handful per process.
    endpoints: Mutex<HashMap<Endpoint, EndpointState>>,
    /// The URLs whose last request failed, each logged once.
    failing: Mutex<HashSet<String>>,
}

impl Scraper {
    pub fn new() -> Option<Self> {
        let client = Client::builder()
            .timeout(TIMEOUT)
            .build()
            .map_err(|e| warn!("HTTP scraping disabled: {e}"))
            .ok()?;
        Some(Self {
            client,
            endpoints: Mutex::new(HashMap::new()),
            failing: Mutex::new(HashSet::new()),
        })
    }

    /// Unwraps a request's result, logging a failure once until the URL
    /// is read successfully again.
    fn check<T>(&self, url: &str, result: Result<T, String>) -> Option<T> {
        let mut failing = self.failing.lock().unwrap_or_else(|e| e.into_inner());
        match result {
            Ok(value) => {
                failing.remove(url);
                Some(value)
            }
            Err(e) => {
                if failing.insert(url.to_string()) {
                    warn!("Failed to scrape {url}: {e}");
                } else {
                    debug!("Failed to scrape {url}: {e}");
                }
                None
            }
        }
    }
}

#[async_trait::async_trait]
impl Collector for Scraper {
    async fn collect_metrics(
        &self,
        scopes: &[Scope],
    ) -> Result<Sample, Box<dyn std::error::Error>> {
        let endpoints = group_by(scopes, |scope| {
            scope
                .open_metrics_endpoints
                .iter()
                .map(|(name, url)| Endpoint {
                    name: name.clone(),
                    url: url.clone(),
                    headers: scope.open_metrics_http_headers.clone(),
                    filters: scope.open_metrics_filters.clone(),
                })
                .collect()
        });
        let exporters = group_by(scopes, |scope| {
            if scope.dcgm_exporter.is_empty() {
                Vec::new()
            } else {
                vec![(
                    scope.dcgm_exporter.clone(),
                    scope.open_metrics_http_headers.clone(),
                )]
            }
        });
        if endpoints.is_empty() && exporters.is_empty() {
            return Ok(Sample::default());
        }

        // One attempt per sweep; the next sweep retries.
        let scrapes: Vec<_> = endpoints
            .iter()
            .map(|(endpoint, _)| {
                let client = self.client.clone();
                let url = endpoint.url.clone();
                let headers = endpoint.headers.clone();
                tokio::spawn(async move {
                    request(&client, &url, &headers)
                        .await?
                        .text()
                        .await
                        .map_err(|e| e.to_string())
                })
            })
            .collect();
        let queries: Vec<_> = exporters
            .iter()
            .map(|((exporter, headers), _)| {
                let client = self.client.clone();
                let exporter = exporter.clone();
                let headers = headers.clone();
                tokio::spawn(async move { query_dcgm(&client, &exporter, &headers).await })
            })
            .collect();

        let mut sample = Sample::default();
        for scope in scopes {
            sample.scoped.entry(scope.clone()).or_default();
        }

        let mut scraped = Vec::with_capacity(scrapes.len());
        for scrape in scrapes {
            scraped.push(scrape.await.unwrap_or_else(|e| Err(e.to_string())));
        }
        let mut queried = Vec::with_capacity(queries.len());
        for query in queries {
            queried.push(query.await.unwrap_or_else(|e| Err(e.to_string())));
        }

        // The label indexes outlive a paused run, as they did in wandb-core.
        let mut states = self.endpoints.lock().unwrap_or_else(|e| e.into_inner());
        for ((endpoint, scopes), result) in endpoints.iter().zip(scraped) {
            let Some(text) = self.check(&endpoint.url, result) else {
                continue;
            };
            let state = states
                .entry(endpoint.clone())
                .or_insert_with(|| EndpointState::new(&endpoint.filters));
            let metrics = state.metrics(&endpoint.name, &text);
            for scope in scopes {
                sample
                    .scoped
                    .get_mut(scope)
                    .unwrap()
                    .metrics
                    .extend(metrics.iter().cloned());
            }
        }
        for (((exporter, _), scopes), result) in exporters.iter().zip(queried) {
            let Some(samples) = self.check(exporter, result) else {
                continue;
            };
            let metrics: Vec<(String, f64)> = samples
                .iter()
                .filter_map(|sample| Some((sample.key()?, sample.value)))
                .collect();
            for scope in scopes {
                sample
                    .scoped
                    .get_mut(scope)
                    .unwrap()
                    .metrics
                    .extend(metrics.iter().cloned());
            }
        }
        Ok(sample)
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        EnvironmentRecord::default()
    }

    /// Lists the GPUs a DCGM exporter reports a model name and UUID for.
    async fn probe(&self, request: &GetMetadataRequest, metadata: &mut EnvironmentRecord) {
        if request.dcgm_exporter.is_empty() {
            return;
        }
        let headers = request
            .open_metrics_http_headers
            .iter()
            .map(|(name, value)| (name.clone(), value.clone()))
            .collect();
        let result = query_dcgm(&self.client, &request.dcgm_exporter, &headers).await;
        let Some(samples) = self.check(&request.dcgm_exporter, result) else {
            return;
        };
        let gpus: Vec<GpuNvidiaInfo> = samples
            .into_iter()
            .filter(|sample| !sample.model_name.is_empty() && !sample.uuid.is_empty())
            .map(|sample| GpuNvidiaInfo {
                name: sample.model_name,
                uuid: sample.uuid,
                ..Default::default()
            })
            .collect();
        if let Some(first) = gpus.first() {
            metadata.gpu_count = gpus.len() as u32;
            metadata.gpu_type = first.name.clone();
            metadata.gpu_nvidia.extend(gpus);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEXT: &str = "\
# TYPE DCGM_FI_DEV_GPU_TEMP gauge
DCGM_FI_DEV_GPU_TEMP{gpu=\"0\",pod=\"wandb-1\"} 40
DCGM_FI_DEV_GPU_TEMP{gpu=\"1\",pod=\"other\"} 41
# TYPE requests_total counter
requests_total 7
untyped_metric 3
";

    fn filter(metric_regex: &str, label_regexes: &[(&str, &str)]) -> Filter {
        Filter {
            metric_regex: metric_regex.to_string(),
            label_regexes: label_regexes
                .iter()
                .map(|(label, regex)| (label.to_string(), regex.to_string()))
                .collect(),
        }
    }

    fn keys(filters: &[Filter]) -> Vec<String> {
        EndpointState::new(filters)
            .metrics("node1", TEXT)
            .into_iter()
            .map(|(key, _)| key)
            .collect()
    }

    #[test]
    fn filters_keep_the_samples_any_filter_matches() {
        let temp0 = "openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.0";
        let temp1 = "openmetrics.node1.DCGM_FI_DEV_GPU_TEMP.1";
        let requests = "openmetrics.node1.requests_total.0";

        // No filters keeps every gauge and counter.
        assert_eq!(keys(&[]), [temp0, temp1, requests]);
        // A sequence-style filter matches "<endpoint>.<metric>".
        assert_eq!(keys(&[filter("node[0-9].requests", &[])]), [requests]);
        assert_eq!(keys(&[filter("node[2-9].requests", &[])]), [""; 0]);
        // A mapping-style filter also needs every label regex to match.
        assert_eq!(keys(&[filter(".*TEMP", &[("pod", "^wandb-")])]), [temp0]);
        assert_eq!(
            keys(&[
                filter(".*TEMP", &[("pod", "^wandb-")]),
                filter(".*TEMP", &[("gpu", "1")])
            ]),
            [temp0, temp1]
        );
        // A label the sample lacks fails the filter.
        assert_eq!(keys(&[filter(".*", &[("pod", ".*")])]), [temp0, temp1]);
        // A filter that does not compile matches nothing.
        assert_eq!(keys(&[filter("(", &[])]), [""; 0]);
    }

    #[test]
    fn label_sets_keep_their_index_across_scrapes() {
        let mut state = EndpointState::new(&[]);
        let first = state.metrics("n", "# TYPE m gauge\nm{a=\"1\"} 1\nm{a=\"2\"} 2\n");
        let second = state.metrics(
            "n",
            "# TYPE m gauge\nm{a=\"2\"} 5\nm{a=\"3\"} 6\nm{a=\"1\"} 4\n",
        );
        let keys = |metrics: &[(String, f64)]| {
            metrics
                .iter()
                .map(|(key, value)| format!("{key}={value}"))
                .collect::<Vec<_>>()
        };
        assert_eq!(keys(&first), ["openmetrics.n.m.0=1", "openmetrics.n.m.1=2"]);
        assert_eq!(
            keys(&second),
            [
                "openmetrics.n.m.1=5",
                "openmetrics.n.m.2=6",
                "openmetrics.n.m.0=4"
            ]
        );
    }

    #[test]
    fn label_values_may_contain_commas_and_escaped_quotes() {
        let labels = parse_labels(r#"a="x,y", b="say \"hi\"""#).unwrap();
        assert_eq!(labels["a"], "x,y");
        assert_eq!(labels["b"], "say \"hi\"");
    }

    #[test]
    fn promql_url_splits_into_base_and_queries() {
        assert_eq!(
            parse_promql_url(
                "http://localhost:9090/api/v1/query?query=q1&query=q2{node=\"l1337\"}"
            )
            .unwrap(),
            (
                "http://localhost:9090".to_string(),
                vec!["q1".to_string(), "q2{node=\"l1337\"}".to_string()]
            )
        );
        assert_eq!(
            parse_promql_url("https://gateway/api/v1/query?query=q")
                .unwrap()
                .0,
            "https://gateway"
        );
        assert!(parse_promql_url("http://localhost:9090/metrics").is_err());
        assert!(parse_promql_url("://invalid-url").is_err());
    }
}
