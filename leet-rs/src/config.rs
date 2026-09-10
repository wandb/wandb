//! Application configuration with persistence to `wandb-leet.json`.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::theme::{
    COLOR_MODE_PER_PLOT, COLOR_MODE_PER_SERIES, DEFAULT_COLOR_SCHEME,
    DEFAULT_FRENCH_FRIES_COLOR_SCHEME, DEFAULT_METRICS_GRID_COLS, DEFAULT_METRICS_GRID_ROWS,
    DEFAULT_PER_PLOT_COLOR_SCHEME, DEFAULT_SYMON_GRID_COLS, DEFAULT_SYMON_GRID_ROWS,
    DEFAULT_SYSTEM_GRID_COLS, DEFAULT_SYSTEM_GRID_ROWS, DEFAULT_TAG_COLOR_SCHEME,
    DEFAULT_WORKSPACE_METRICS_GRID_COLS, DEFAULT_WORKSPACE_METRICS_GRID_ROWS,
    DEFAULT_WORKSPACE_SYSTEM_GRID_COLS, DEFAULT_WORKSPACE_SYSTEM_GRID_ROWS, is_known_color_scheme,
};

const ENV_CONFIG_DIR: &str = "WANDB_CONFIG_DIR";
const LEET_CONFIG_NAME: &str = "wandb-leet.json";

/// Chart grid size constraints.
pub const MIN_GRID_SIZE: i32 = 1;
pub const MAX_GRID_SIZE: i32 = 9;

pub const DEFAULT_SYSTEM_COLOR_SCHEME: &str = "wandb-vibe-10";
pub const DEFAULT_SINGLE_RUN_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;
pub const DEFAULT_SYSTEM_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;
pub const DEFAULT_SYSTEM_TAIL_WINDOW_MINS: i32 = 10;

pub const DEFAULT_HEARTBEAT_INTERVAL: i32 = 15; // seconds

pub const DEFAULT_MEDIA_GRID_ROWS: i32 = 1;
pub const DEFAULT_MEDIA_GRID_COLS: i32 = 2;
pub const DEFAULT_WORKSPACE_MEDIA_GRID_ROWS: i32 = 1;
pub const DEFAULT_WORKSPACE_MEDIA_GRID_COLS: i32 = 2;

// Startup modes control what LEET does when launched without a run path.
pub const STARTUP_MODE_WORKSPACE_LATEST: &str = "workspace_latest";
pub const STARTUP_MODE_SINGLE_RUN_LATEST: &str = "single_run_latest";
pub const DEFAULT_STARTUP_MODE: &str = STARTUP_MODE_WORKSPACE_LATEST;

/// Grid dimensions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct GridConfig {
    pub rows: i32,
    pub cols: i32,
}

/// User-set pane proportions from mouse resizing, as fractions of the
/// terminal size. `None` fields use the built-in golden-ratio defaults.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct LayoutOverrides {
    /// Left sidebar width as a fraction of the terminal width.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub left_sidebar: Option<f64>,
    /// Right sidebar width as a fraction of the terminal width.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub right_sidebar: Option<f64>,
    /// Stacked pane heights as fractions of the terminal height.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub system: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub logs: Option<f64>,
}

impl LayoutOverrides {
    pub fn is_default(&self) -> bool {
        *self == Self::default()
    }

    fn normalize(&mut self) {
        for field in [
            &mut self.left_sidebar,
            &mut self.right_sidebar,
            &mut self.system,
            &mut self.media,
            &mut self.logs,
        ] {
            if let Some(v) = field {
                if v.is_finite() {
                    *v = v.clamp(0.05, 0.9);
                } else {
                    *field = None;
                }
            }
        }
    }
}

/// The pending grid-size key target (set by grid config keybindings, consumed
/// by the next 1-9 keypress).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum GridConfigTarget {
    #[default]
    None,
    MetricsRows,
    MetricsCols,
    SystemRows,
    SystemCols,
    MediaRows,
    MediaCols,
    WorkspaceMetricsRows,
    WorkspaceMetricsCols,
    WorkspaceSystemRows,
    WorkspaceSystemCols,
    WorkspaceMediaRows,
    WorkspaceMediaCols,
    SymonRows,
    SymonCols,
}

/// The application configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Controls what happens when LEET is launched without a run path:
    /// `workspace_latest` or `single_run_latest`.
    pub startup_mode: String,

    /// Metrics chart grid dimensions in single-run mode.
    pub metrics_grid: GridConfig,
    /// System metrics chart grid dimensions in single-run mode.
    pub system_grid: GridConfig,
    /// Media thumbnail grid dimensions in single-run mode.
    pub media_grid: GridConfig,

    // Grid dimensions in workspace view.
    pub workspace_metrics_grid: GridConfig,
    pub workspace_system_grid: GridConfig,
    pub workspace_media_grid: GridConfig,

    /// Standalone system monitor chart grid dimensions.
    pub symon_grid: GridConfig,

    /// Palette for main run metrics charts (and run list colors).
    pub color_scheme: String,
    /// Palette for run tags in the overview sidebar.
    pub tag_color_scheme: String,
    /// Palette for single-run view in per-plot mode.
    pub per_plot_color_scheme: String,
    /// Palette for system charts.
    pub system_color_scheme: String,
    /// Palette for percentage heatmaps (French Fries plots).
    pub french_fries_color_scheme: String,
    /// Color system charts per plot or per series.
    pub system_color_mode: String,
    /// Default live tail window for system charts (minutes).
    pub system_tail_window_minutes: i32,
    /// Color single-run charts per plot or per stable run-id color.
    pub single_run_color_mode: String,

    /// Heartbeat interval in seconds for live runs.
    #[serde(rename = "heartbeat_interval_seconds")]
    pub heartbeat_interval: i32,

    // Single-run view pane visibility states.
    pub left_sidebar_visible: bool,
    pub right_sidebar_visible: bool,
    pub metrics_grid_visible: bool,
    pub console_logs_visible: bool,
    pub media_visible: bool,

    // Workspace view pane visibility states.
    pub workspace_overview_visible: bool,
    pub workspace_metrics_grid_visible: bool,
    pub workspace_system_metrics_visible: bool,
    pub workspace_console_logs_visible: bool,
    pub workspace_media_visible: bool,

    // Custom pane proportions from mouse resizing.
    #[serde(skip_serializing_if = "LayoutOverrides::is_default")]
    pub workspace_layout: LayoutOverrides,
    #[serde(skip_serializing_if = "LayoutOverrides::is_default")]
    pub run_layout: LayoutOverrides,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            startup_mode: DEFAULT_STARTUP_MODE.to_string(),
            metrics_grid: GridConfig {
                rows: DEFAULT_METRICS_GRID_ROWS,
                cols: DEFAULT_METRICS_GRID_COLS,
            },
            system_grid: GridConfig {
                rows: DEFAULT_SYSTEM_GRID_ROWS,
                cols: DEFAULT_SYSTEM_GRID_COLS,
            },
            media_grid: GridConfig {
                rows: DEFAULT_MEDIA_GRID_ROWS,
                cols: DEFAULT_MEDIA_GRID_COLS,
            },
            workspace_metrics_grid: GridConfig {
                rows: DEFAULT_WORKSPACE_METRICS_GRID_ROWS,
                cols: DEFAULT_WORKSPACE_METRICS_GRID_COLS,
            },
            workspace_system_grid: GridConfig {
                rows: DEFAULT_WORKSPACE_SYSTEM_GRID_ROWS,
                cols: DEFAULT_WORKSPACE_SYSTEM_GRID_COLS,
            },
            workspace_media_grid: GridConfig {
                rows: DEFAULT_WORKSPACE_MEDIA_GRID_ROWS,
                cols: DEFAULT_WORKSPACE_MEDIA_GRID_COLS,
            },
            symon_grid: GridConfig {
                rows: DEFAULT_SYMON_GRID_ROWS,
                cols: DEFAULT_SYMON_GRID_COLS,
            },
            color_scheme: DEFAULT_COLOR_SCHEME.to_string(),
            tag_color_scheme: DEFAULT_TAG_COLOR_SCHEME.to_string(),
            per_plot_color_scheme: DEFAULT_PER_PLOT_COLOR_SCHEME.to_string(),
            system_color_scheme: DEFAULT_SYSTEM_COLOR_SCHEME.to_string(),
            french_fries_color_scheme: DEFAULT_FRENCH_FRIES_COLOR_SCHEME.to_string(),
            system_color_mode: DEFAULT_SYSTEM_COLOR_MODE.to_string(),
            system_tail_window_minutes: DEFAULT_SYSTEM_TAIL_WINDOW_MINS,
            single_run_color_mode: DEFAULT_SINGLE_RUN_COLOR_MODE.to_string(),
            heartbeat_interval: DEFAULT_HEARTBEAT_INTERVAL,
            left_sidebar_visible: true,
            right_sidebar_visible: true,
            metrics_grid_visible: true,
            console_logs_visible: false,
            media_visible: false,
            workspace_overview_visible: true,
            workspace_metrics_grid_visible: true,
            workspace_system_metrics_visible: false,
            workspace_console_logs_visible: false,
            workspace_media_visible: false,
            workspace_layout: LayoutOverrides::default(),
            run_layout: LayoutOverrides::default(),
        }
    }
}

impl Config {
    /// Ensures all values are within valid ranges.
    pub fn normalize(&mut self) {
        for grid in [
            &mut self.metrics_grid,
            &mut self.system_grid,
            &mut self.media_grid,
            &mut self.workspace_metrics_grid,
            &mut self.workspace_system_grid,
            &mut self.workspace_media_grid,
            &mut self.symon_grid,
        ] {
            grid.rows = grid.rows.clamp(MIN_GRID_SIZE, MAX_GRID_SIZE);
            grid.cols = grid.cols.clamp(MIN_GRID_SIZE, MAX_GRID_SIZE);
        }

        normalize_scheme(&mut self.color_scheme, DEFAULT_COLOR_SCHEME);
        normalize_scheme(
            &mut self.per_plot_color_scheme,
            DEFAULT_PER_PLOT_COLOR_SCHEME,
        );
        normalize_scheme(&mut self.system_color_scheme, DEFAULT_SYSTEM_COLOR_SCHEME);
        normalize_scheme(
            &mut self.french_fries_color_scheme,
            DEFAULT_FRENCH_FRIES_COLOR_SCHEME,
        );
        normalize_scheme(&mut self.tag_color_scheme, DEFAULT_TAG_COLOR_SCHEME);

        normalize_color_mode(&mut self.system_color_mode, DEFAULT_SYSTEM_COLOR_MODE);
        normalize_color_mode(
            &mut self.single_run_color_mode,
            DEFAULT_SINGLE_RUN_COLOR_MODE,
        );

        if self.heartbeat_interval <= 0 {
            self.heartbeat_interval = DEFAULT_HEARTBEAT_INTERVAL;
        }
        if self.system_tail_window_minutes <= 0 {
            self.system_tail_window_minutes = DEFAULT_SYSTEM_TAIL_WINDOW_MINS;
        }
        if self.startup_mode != STARTUP_MODE_WORKSPACE_LATEST
            && self.startup_mode != STARTUP_MODE_SINGLE_RUN_LATEST
        {
            self.startup_mode = DEFAULT_STARTUP_MODE.to_string();
        }

        self.workspace_layout.normalize();
        self.run_layout.normalize();
    }

    /// The live tail window for system charts, in seconds.
    pub fn system_tail_window_secs(&self) -> f64 {
        self.system_tail_window_minutes as f64 * 60.0
    }
}

fn normalize_scheme(scheme: &mut String, fallback: &str) {
    if !is_known_color_scheme(scheme) {
        *scheme = fallback.to_string();
    }
}

fn normalize_color_mode(mode: &mut String, fallback: &str) {
    if mode != COLOR_MODE_PER_PLOT && mode != COLOR_MODE_PER_SERIES {
        *mode = fallback.to_string();
    }
}

/// Manages application configuration with automatic persistence to disk.
pub struct ConfigManager {
    path: PathBuf,
    config: Config,
    pending_grid_config: GridConfigTarget,
}

impl ConfigManager {
    /// Loads the configuration from `path`, creating it with defaults if
    /// missing. Load/save errors are reported to stderr but not fatal.
    pub fn new(path: PathBuf) -> Self {
        let mut cm = Self {
            path,
            config: Config::default(),
            pending_grid_config: GridConfigTarget::None,
        };
        if let Err(err) = cm.load_or_create() {
            eprintln!("config: error loading or creating: {err}");
        }
        cm
    }

    fn load_or_create(&mut self) -> std::io::Result<()> {
        match std::fs::read(&self.path) {
            Ok(data) => {
                self.config = serde_json::from_slice(&data)
                    .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
                self.config.normalize();
                Ok(())
            }
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
                if let Some(dir) = self.path.parent() {
                    let _ = std::fs::create_dir_all(dir);
                }
                self.save()
            }
            Err(err) => Err(err),
        }
    }

    /// Writes the current configuration to disk atomically.
    fn save(&self) -> std::io::Result<()> {
        let data = serde_json::to_vec_pretty(&self.config)?;
        let temp_path = self.path.with_extension("json.tmp");
        std::fs::write(&temp_path, data)?;
        std::fs::rename(&temp_path, &self.path)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn config(&self) -> &Config {
        &self.config
    }

    /// Mutates the config, then normalizes and persists it.
    pub fn update(&mut self, f: impl FnOnce(&mut Config)) {
        f(&mut self.config);
        self.config.normalize();
        if let Err(err) = self.save() {
            eprintln!("config: error saving: {err}");
        }
    }

    /// Replaces the full config (validated) and persists it.
    pub fn set_config(&mut self, cfg: Config) {
        self.update(|c| *c = cfg);
    }

    pub fn is_awaiting_grid_config(&self) -> bool {
        self.pending_grid_config != GridConfigTarget::None
    }

    pub fn set_pending_grid_config(&mut self, target: GridConfigTarget) {
        self.pending_grid_config = target;
    }

    /// Sets a value for the pending grid config target. Returns the status
    /// message, or None if nothing was pending.
    pub fn set_grid_config(&mut self, num: i32) -> Option<String> {
        if !(MIN_GRID_SIZE..=MAX_GRID_SIZE).contains(&num) {
            return Option::None;
        }

        use GridConfigTarget::*;
        let (label, field): (&str, fn(&mut Config) -> &mut i32) = match self.pending_grid_config {
            None => return Option::None,
            MetricsRows => ("Metrics grid rows", |c| &mut c.metrics_grid.rows),
            MetricsCols => ("Metrics grid columns", |c| &mut c.metrics_grid.cols),
            SystemRows => ("System grid rows", |c| &mut c.system_grid.rows),
            SystemCols => ("System grid columns", |c| &mut c.system_grid.cols),
            MediaRows => ("Media grid rows", |c| &mut c.media_grid.rows),
            MediaCols => ("Media grid columns", |c| &mut c.media_grid.cols),
            WorkspaceMetricsRows => ("Workspace metrics grid rows", |c| {
                &mut c.workspace_metrics_grid.rows
            }),
            WorkspaceMetricsCols => ("Workspace metrics grid columns", |c| {
                &mut c.workspace_metrics_grid.cols
            }),
            WorkspaceSystemRows => ("Workspace system grid rows", |c| {
                &mut c.workspace_system_grid.rows
            }),
            WorkspaceSystemCols => ("Workspace system grid columns", |c| {
                &mut c.workspace_system_grid.cols
            }),
            WorkspaceMediaRows => ("Workspace media grid rows", |c| {
                &mut c.workspace_media_grid.rows
            }),
            WorkspaceMediaCols => ("Workspace media grid columns", |c| {
                &mut c.workspace_media_grid.cols
            }),
            SymonRows => ("Symon grid rows", |c| &mut c.symon_grid.rows),
            SymonCols => ("Symon grid columns", |c| &mut c.symon_grid.cols),
        };

        self.update(|c| *field(c) = num);
        Some(format!("{label} set to {num}"))
    }

    /// The status message to display when awaiting grid config input.
    pub fn grid_config_status(&self) -> &'static str {
        use GridConfigTarget::*;
        match self.pending_grid_config {
            MetricsCols | WorkspaceMetricsCols => {
                "Press 1-9 to set metrics grid columns (ESC to cancel)"
            }
            MetricsRows | WorkspaceMetricsRows => {
                "Press 1-9 to set metrics grid rows (ESC to cancel)"
            }
            SystemCols | WorkspaceSystemCols | SymonCols => {
                "Press 1-9 to set system grid columns (ESC to cancel)"
            }
            SystemRows | WorkspaceSystemRows | SymonRows => {
                "Press 1-9 to set system grid rows (ESC to cancel)"
            }
            MediaCols | WorkspaceMediaCols => "Press 1-9 to set media grid columns (ESC to cancel)",
            MediaRows | WorkspaceMediaRows => "Press 1-9 to set media grid rows (ESC to cancel)",
            None => "",
        }
    }
}

/// The path where the config should be stored.
///
/// Matches the Python logic (same directory as the system "settings" file),
/// with fallbacks to the user config dir and a temp dir.
pub fn leet_config_path() -> PathBuf {
    // 1) Honor WANDB_CONFIG_DIR (like in Python).
    if let Ok(raw) = std::env::var(ENV_CONFIG_DIR) {
        let raw = raw.trim();
        if !raw.is_empty()
            && let Some(p) = config_path_from_dir(Path::new(raw))
        {
            return p;
        }
    }

    // 2) Default to ~/.config/wandb (like in Python).
    if let Some(home) = home_dir()
        && let Some(p) = config_path_from_dir(&home.join(".config").join("wandb"))
    {
        return p;
    }

    // 3) Last resort: the temp dir.
    std::env::temp_dir().join(LEET_CONFIG_NAME)
}

fn config_path_from_dir(dir: &Path) -> Option<PathBuf> {
    let dir = expand_tilde(dir);
    ensure_writable_dir(&dir).ok()?;
    Some(dir.join(LEET_CONFIG_NAME))
}

fn expand_tilde(p: &Path) -> PathBuf {
    if let Ok(rest) = p.strip_prefix("~")
        && let Some(home) = home_dir()
    {
        return home.join(rest);
    }
    p.to_path_buf()
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

/// Verifies directory writability without leaving files behind.
fn ensure_writable_dir(dir: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dir)?;
    let probe = dir.join(".wandb-leet-writecheck");
    std::fs::write(&probe, b"")?;
    std::fs::remove_file(&probe)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_and_normalize() {
        let mut c = Config::default();
        c.metrics_grid.rows = 42;
        c.color_scheme = "nonsense".to_string();
        c.heartbeat_interval = -1;
        c.startup_mode = "bogus".to_string();
        c.normalize();
        assert_eq!(c.metrics_grid.rows, MAX_GRID_SIZE);
        assert_eq!(c.color_scheme, DEFAULT_COLOR_SCHEME);
        assert_eq!(c.heartbeat_interval, DEFAULT_HEARTBEAT_INTERVAL);
        assert_eq!(c.startup_mode, DEFAULT_STARTUP_MODE);
    }

    #[test]
    fn round_trip_persistence() {
        let dir = std::env::temp_dir().join(format!("leet-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join(LEET_CONFIG_NAME);
        {
            let mut cm = ConfigManager::new(path.clone());
            cm.update(|c| c.metrics_grid.rows = 5);
        }
        {
            let cm = ConfigManager::new(path.clone());
            assert_eq!(cm.config().metrics_grid.rows, 5);
        }
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn grid_config_targets() {
        let dir = std::env::temp_dir().join(format!("leet-test-gct-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut cm = ConfigManager::new(dir.join(LEET_CONFIG_NAME));
        assert!(!cm.is_awaiting_grid_config());
        cm.set_pending_grid_config(GridConfigTarget::SystemCols);
        assert!(cm.is_awaiting_grid_config());
        let msg = cm.set_grid_config(4).unwrap();
        assert_eq!(msg, "System grid columns set to 4");
        assert_eq!(cm.config().system_grid.cols, 4);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
