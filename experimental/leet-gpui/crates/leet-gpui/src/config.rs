//! User configuration, a JSON file next to leet's own (`WANDB_CONFIG_DIR`,
//! else `~/.config/wandb`). Key names follow `core/internal/leet/config.go`
//! where the meaning matches; unknown keys survive a round trip.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

const FILE_NAME: &str = "wandb-leet-gpui.json";

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct GridConfig {
    pub rows: usize,
    pub cols: usize,
}

/// Pane sizes as fractions of the window; zero means the default split.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Layout {
    pub left_sidebar: f64,
    pub right_sidebar: f64,
    pub system: f64,
    pub logs: f64,
    pub overview_env: f64,
    pub overview_config: f64,
    pub overview_summary: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    pub workspace_metrics_grid: GridConfig,
    pub workspace_system_grid: GridConfig,
    pub workspace_layout: Layout,
    pub workspace_overview_visible: bool,
    pub workspace_metrics_grid_visible: bool,
    pub workspace_system_metrics_visible: bool,
    pub workspace_console_logs_visible: bool,
    pub smoothing: f64,
    #[serde(flatten)]
    pub other: serde_json::Map<String, serde_json::Value>,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            workspace_metrics_grid: GridConfig { rows: 3, cols: 3 },
            workspace_system_grid: GridConfig { rows: 3, cols: 3 },
            workspace_layout: Layout::default(),
            workspace_overview_visible: true,
            workspace_metrics_grid_visible: true,
            workspace_system_metrics_visible: false,
            workspace_console_logs_visible: false,
            smoothing: 0.0,
            other: serde_json::Map::new(),
        }
    }
}

pub struct ConfigFile {
    pub config: Config,
    path: PathBuf,
}

impl ConfigFile {
    pub fn load() -> Self {
        let path = config_path();
        let config = std::fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_default();
        ConfigFile { config, path }
    }

    pub fn save(&self) {
        if let Some(dir) = self.path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(json) = serde_json::to_vec_pretty(&self.config) {
            let _ = std::fs::write(&self.path, json);
        }
    }
}

fn config_path() -> PathBuf {
    let dir = std::env::var_os("WANDB_CONFIG_DIR")
        .map(PathBuf::from)
        .filter(|dir| !dir.as_os_str().is_empty())
        .or_else(|| {
            std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config").join("wandb"))
        })
        .unwrap_or_else(std::env::temp_dir);
    dir.join(FILE_NAME)
}
