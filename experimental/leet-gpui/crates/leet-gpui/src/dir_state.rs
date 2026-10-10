//! Per-directory memory shared with the terminal LEET: `.wandb-leet.json`
//! inside the wandb directory remembers the filters, the selected runs, and
//! the newest run at the time of saving. Keys this app does not know, such
//! as the terminal's pinned run, are kept as they are.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

const FILE_NAME: &str = ".wandb-leet.json";

pub struct DirState {
    path: PathBuf,
    value: Map<String, Value>,
}

impl DirState {
    pub fn load(wandb_dir: &Path) -> Self {
        let path = wandb_dir.join(FILE_NAME);
        let value = std::fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
            .and_then(|value| match value {
                Value::Object(map) => Some(map),
                _ => None,
            })
            .unwrap_or_default();
        DirState { path, value }
    }

    pub fn selected_runs(&self) -> Vec<String> {
        strings(self.value.get("selected_runs"))
    }

    pub fn latest_run(&self) -> Option<String> {
        string(self.value.get("latest_run"))
    }

    /// The saved query of a filter such as `runs_filter` or `metrics_filter`.
    pub fn filter(&self, name: &str) -> String {
        string(self.value.get(name).and_then(|f| f.get("query"))).unwrap_or_default()
    }

    pub fn set_filter(&mut self, name: &str, query: &str) {
        match self.value.get_mut(name) {
            Some(Value::Object(filter)) => {
                filter.insert("query".into(), Value::String(query.to_string()));
            }
            _ => {
                self.value.insert(name.into(), json!({ "query": query }));
            }
        }
        self.save();
    }

    pub fn set_selection(&mut self, selected: &BTreeSet<String>, latest: Option<&str>) {
        self.set_or_remove(
            "selected_runs",
            (!selected.is_empty()).then(|| json!(selected)),
        );
        self.set_or_remove("latest_run", latest.map(|run| json!(run)));
        self.save();
    }

    fn set_or_remove(&mut self, key: &str, value: Option<Value>) {
        match value {
            Some(value) => {
                self.value.insert(key.into(), value);
            }
            None => {
                self.value.remove(key);
            }
        }
    }

    fn save(&self) {
        if let Ok(json) = serde_json::to_vec_pretty(&Value::Object(self.value.clone())) {
            let _ = std::fs::write(&self.path, json);
        }
    }
}

fn string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}
