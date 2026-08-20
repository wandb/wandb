//! Port of `core/internal/leet/config.go`: application configuration,
//! `ConfigManager` with auto-persisting setters, and the on-disk config
//! path resolution.
//!
//! CROSS-COMPAT: the config file (`wandb-leet.json`) is shared with the Go
//! binary. Serialization must keep Go's struct declaration order, and reads
//! must tolerate unknown fields (Go ignores unknowns) and keep defaults for
//! missing fields (Go unmarshals into a pre-populated struct).

use std::env;
use std::fs;
use std::io;
#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

/// gridConfigTarget selects which grid dimension a pending 1-9 keypress
/// configures.
// PARITY: unexported `gridConfigTarget` in Go; pub here because the key
// handling lives in leet-tui (crate boundary vs Go package).
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

pub const ENV_CONFIG_DIR: &str = "WANDB_CONFIG_DIR";
pub const LEET_CONFIG_NAME: &str = "wandb-leet.json";

// Chart grid size constraints.
pub const MIN_GRID_SIZE: i64 = 1;
pub const MAX_GRID_SIZE: i64 = 9;

/// Each chart gets next color.
pub const COLOR_MODE_PER_PLOT: &str = "per_plot";
/// All charts use base color, multi-series differentiate.
pub const COLOR_MODE_PER_SERIES: &str = "per_series";

pub const DEFAULT_COLOR_SCHEME: &str = "wandb-vibe-10";
pub const DEFAULT_PER_PLOT_COLOR_SCHEME: &str = "sunset-glow";
pub const DEFAULT_TAG_COLOR_SCHEME: &str = DEFAULT_COLOR_SCHEME;
pub const DEFAULT_SINGLE_RUN_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;

pub const DEFAULT_SYSTEM_COLOR_SCHEME: &str = "wandb-vibe-10";
pub const DEFAULT_FRENCH_FRIES_COLOR_SCHEME: &str = "viridis";
pub const DEFAULT_SYSTEM_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;
pub const DEFAULT_SYSTEM_TAIL_WINDOW_MINS: i64 = 10;

/// seconds
pub const DEFAULT_HEARTBEAT_INTERVAL: i64 = 15;

pub const DEFAULT_MEDIA_GRID_ROWS: i64 = 1;
pub const DEFAULT_MEDIA_GRID_COLS: i64 = 2;
pub const DEFAULT_WORKSPACE_MEDIA_GRID_ROWS: i64 = 1;
pub const DEFAULT_WORKSPACE_MEDIA_GRID_COLS: i64 = 2;

// PARITY: Go declares the following grid defaults in styles.go:150-163.
// They live here because config.go consumes them and leet-charts depends on
// leet-data (dependency direction); leet-charts must reuse these, not
// redeclare them.
pub const DEFAULT_METRICS_GRID_ROWS: i64 = 4;
pub const DEFAULT_METRICS_GRID_COLS: i64 = 3;
pub const DEFAULT_SYSTEM_GRID_ROWS: i64 = 6;
pub const DEFAULT_SYSTEM_GRID_COLS: i64 = 2;
pub const DEFAULT_WORKSPACE_METRICS_GRID_ROWS: i64 = 3;
pub const DEFAULT_WORKSPACE_METRICS_GRID_COLS: i64 = 3;
pub const DEFAULT_WORKSPACE_SYSTEM_GRID_ROWS: i64 = 3;
pub const DEFAULT_WORKSPACE_SYSTEM_GRID_COLS: i64 = 3;
pub const DEFAULT_SYMON_GRID_ROWS: i64 = 3;
pub const DEFAULT_SYMON_GRID_COLS: i64 = 3;

// Startup modes control what LEET does when launched without a specified run
// path (i.e. `wandb leet` with no PATH).
/// Load workspace view and select latest run.
pub const STARTUP_MODE_WORKSPACE_LATEST: &str = "workspace_latest";
/// Load latest run in the single-run view.
pub const STARTUP_MODE_SINGLE_RUN_LATEST: &str = "single_run_latest";
pub const DEFAULT_STARTUP_MODE: &str = STARTUP_MODE_WORKSPACE_LATEST;

/// Names of the color schemes defined by the `colorSchemes` map.
// PARITY: Go validates scheme names against the `colorSchemes` map declared
// in styles.go:296 (ported to leet-charts). The key set is duplicated here
// because leet-data cannot depend on leet-charts; leet-charts must keep its
// palette map keys in sync with this list (declaration order preserved).
pub const COLOR_SCHEME_NAMES: &[&str] = &[
    "sunset-glow",
    "blush-tide",
    "gilded-lagoon",
    "bootstrap-vibe",
    "wandb-vibe-10",
    "wandb-vibe-20",
    "dusk-shore",
    "clear-signal",
    "traffic-light",
    "viridis",
    "plasma",
    "inferno",
    "magma",
    "cividis",
];

/// Reports whether `name` is a key of the Go `colorSchemes` map.
pub fn is_known_color_scheme(name: &str) -> bool {
    COLOR_SCHEME_NAMES.contains(&name)
}

/// Config stores the application configuration.
///
/// Field declaration order matches the Go struct; serialization order (and
/// therefore the on-disk JSON key order) depends on it.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Config {
    /// StartupMode controls what happens when LEET is launched without
    /// --run-file.
    ///  - workspace_latest: open workspace and auto-select the latest run
    ///  - single_run_latest: open the latest run directly in single-run view
    pub startup_mode: String,

    /// MetricsGrid is the dimensions for the metrics chart grid in
    /// single-run mode.
    pub metrics_grid: GridConfig,

    /// SystemGrid is the dimensions for the system metrics chart grid in
    /// single-run mode.
    pub system_grid: GridConfig,

    /// MediaGrid is the dimensions for the media thumbnail grid in
    /// single-run mode.
    pub media_grid: GridConfig,

    /// Grid dimensions in Workspace view.
    pub workspace_metrics_grid: GridConfig,
    pub workspace_system_grid: GridConfig,
    pub workspace_media_grid: GridConfig,

    /// SymonGrid is the dimensions for the standalone system monitor chart
    /// grid.
    pub symon_grid: GridConfig,

    /// ColorScheme is the color scheme to display the main metrics.
    pub color_scheme: String,

    /// TagColorScheme is the color scheme for run tag badges in the overview
    /// sidebar.
    pub tag_color_scheme: String,

    /// PerPlotColorScheme is the color scheme to use for main metrics
    /// in single-run view when SingleRunColorMode is per_plot.
    /// Gradient palettes work well here.
    pub per_plot_color_scheme: String,

    /// SystemColorScheme is the color scheme for system metrics charts.
    pub system_color_scheme: String,

    /// FrenchFriesColorScheme is the color scheme for French Fries heatmaps.
    pub french_fries_color_scheme: String,

    /// SystemColorMode determines color assignment strategy.
    /// "per_plot": each chart gets next color from palette
    /// "per_series": all single-series charts use base color, multi-series
    /// differentiate
    pub system_color_mode: String,

    /// SystemTailWindowMinutes controls the default live tail window for
    /// system charts. Users can still zoom out to show the full history.
    pub system_tail_window_minutes: i64,

    /// SingleRunColorMode controls how charts are colored in single-run view:
    ///  - per_series: stably-mapped run-id color for all charts
    ///  - per_plot: each chart gets the next color from the palette (nice
    ///    with gradients)
    pub single_run_color_mode: String,

    /// Heartbeat interval in seconds for live runs.
    ///
    /// Heartbeats are used to trigger .wandb file read attempts if no file
    /// watcher events have been seen for a long time for a live file.
    #[serde(rename = "heartbeat_interval_seconds")]
    pub heartbeat_interval: i64,

    // Single-run view sidebar visibility states.
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
}

/// GridConfig represents grid dimensions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct GridConfig {
    pub rows: i64,
    pub cols: i64,
}

impl Default for Config {
    /// The defaults NewConfigManager seeds before loading (config.go:168-217).
    fn default() -> Self {
        Config {
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
            startup_mode: DEFAULT_STARTUP_MODE.to_string(),
            color_scheme: DEFAULT_COLOR_SCHEME.to_string(),
            per_plot_color_scheme: DEFAULT_PER_PLOT_COLOR_SCHEME.to_string(),
            tag_color_scheme: DEFAULT_TAG_COLOR_SCHEME.to_string(),
            single_run_color_mode: DEFAULT_SINGLE_RUN_COLOR_MODE.to_string(),
            system_color_scheme: DEFAULT_SYSTEM_COLOR_SCHEME.to_string(),
            french_fries_color_scheme: DEFAULT_FRENCH_FRIES_COLOR_SCHEME.to_string(),
            system_color_mode: DEFAULT_SYSTEM_COLOR_MODE.to_string(),
            system_tail_window_minutes: DEFAULT_SYSTEM_TAIL_WINDOW_MINS,
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
        }
    }
}

/// The kind of a [`Config`] field, for the config editor schema
/// (`configeditorfields.go`, ported in leet-tui, Phase 6).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConfigFieldKind {
    Str,
    Int,
    Bool,
    /// Nested [`GridConfig`] struct; the editor recurses into
    /// [`GRID_CONFIG_FIELDS`], treating this field's `desc` as the group
    /// description for its children.
    Grid,
}

/// One row of the config-field metadata table: a `Config` struct field's
/// JSON name plus its parsed `leet:"..."` struct tag.
///
/// Rust has no struct tags; this table carries the exact tag metadata from
/// the Go `Config`/`GridConfig` declarations so the Phase-6 config editor
/// can rebuild the same schema (`buildConfigEditorFields`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConfigFieldDescriptor {
    /// The `json:"..."` tag name.
    pub json_name: &'static str,
    pub kind: ConfigFieldKind,
    /// `leet:"label=..."` — display-label override; `""` if absent.
    pub label: &'static str,
    /// `leet:"desc=..."` — editor footer description (group description for
    /// [`ConfigFieldKind::Grid`] fields); `""` if absent.
    pub desc: &'static str,
    /// `leet:"options=..."` — enum options provider name
    /// (`"colorSchemes"`, `"colorModes"`, `"startupModes"`); `""` if absent.
    pub options: &'static str,
    /// `leet:"min=..."` — minimum for int fields; `None` if absent.
    pub min: Option<i64>,
    /// `leet:"max=..."` — maximum for int fields; `None` if absent.
    pub max: Option<i64>,
}

const fn field(json_name: &'static str, kind: ConfigFieldKind) -> ConfigFieldDescriptor {
    ConfigFieldDescriptor {
        json_name,
        kind,
        label: "",
        desc: "",
        options: "",
        min: None,
        max: None,
    }
}

/// Tag metadata for every `Config` field, in Go struct declaration order.
pub const CONFIG_FIELDS: &[ConfigFieldDescriptor] = &[
    ConfigFieldDescriptor {
        label: "Startup mode",
        desc: "Initial view when launched without a run path.",
        options: "startupModes",
        ..field("startup_mode", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        desc: "main metrics grid",
        ..field("metrics_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "system metrics grid",
        ..field("system_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "single-run media grid",
        ..field("media_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "workspace metrics grid",
        ..field("workspace_metrics_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "workspace system metrics grid",
        ..field("workspace_system_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "workspace media grid",
        ..field("workspace_media_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "standalone system metrics grid",
        ..field("symon_grid", ConfigFieldKind::Grid)
    },
    ConfigFieldDescriptor {
        desc: "Palette for main run metrics charts (and run list colors).",
        options: "colorSchemes",
        ..field("color_scheme", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        label: "Tag color scheme",
        desc: "Palette for run tags in the overview sidebar.",
        options: "colorSchemes",
        ..field("tag_color_scheme", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        label: "Per-plot color scheme",
        desc: "Palette for single-run view in per-plot mode. Gradients look nice here.",
        options: "colorSchemes",
        ..field("per_plot_color_scheme", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        desc: "Palette for system charts.",
        options: "colorSchemes",
        ..field("system_color_scheme", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        label: "Bucketed heatmap color scheme",
        desc: "Palette for percentage heatmaps (French Fries plots). Sequential palettes work best.",
        options: "colorSchemes",
        ..field("french_fries_color_scheme", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        desc: "Color system charts per plot or per series.",
        options: "colorModes",
        ..field("system_color_mode", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        label: "System tail window (min)",
        desc: "Default live tail window for system charts. Zooming out can show full history.",
        min: Some(1),
        ..field("system_tail_window_minutes", ConfigFieldKind::Int)
    },
    ConfigFieldDescriptor {
        label: "Single-run color mode",
        desc: "Color single-run charts per plot or use stable run-id color for all charts.",
        options: "colorModes",
        ..field("single_run_color_mode", ConfigFieldKind::Str)
    },
    ConfigFieldDescriptor {
        label: "Heartbeat interval (sec)",
        desc: "Polling heartbeat for live runs.",
        min: Some(1),
        ..field("heartbeat_interval_seconds", ConfigFieldKind::Int)
    },
    ConfigFieldDescriptor {
        desc: "Show left sidebar in single run view by default.",
        ..field("left_sidebar_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show right sidebar in single run view by default.",
        ..field("right_sidebar_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show metrics grid in single run mode by default.",
        ..field("metrics_grid_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show console logs pane in single run mode by default.",
        ..field("console_logs_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show media pane in single run mode by default.",
        ..field("media_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show run overview sidebar in workspace mode by default.",
        ..field("workspace_overview_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show metrics grid in workspace mode by default.",
        ..field("workspace_metrics_grid_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show system metrics pane in workspace mode by default.",
        ..field("workspace_system_metrics_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show console logs pane in workspace mode by default.",
        ..field("workspace_console_logs_visible", ConfigFieldKind::Bool)
    },
    ConfigFieldDescriptor {
        desc: "Show media pane in workspace mode by default.",
        ..field("workspace_media_visible", ConfigFieldKind::Bool)
    },
];

/// Tag metadata for the `GridConfig` leaf fields (`leet:"min=1,max=9"`).
pub const GRID_CONFIG_FIELDS: &[ConfigFieldDescriptor] = &[
    ConfigFieldDescriptor {
        min: Some(1),
        max: Some(9),
        ..field("rows", ConfigFieldKind::Int)
    },
    ConfigFieldDescriptor {
        min: Some(1),
        max: Some(9),
        ..field("cols", ConfigFieldKind::Int)
    },
];

/// Errors from config load/save/validation.
///
/// Go returns ad-hoc `fmt.Errorf` errors; message text is preserved at the
/// construction sites.
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("failed to write temp config file: {0}")]
    WriteTemp(io::Error),
    #[error("failed to rename tmp config file: {0}")]
    Rename(io::Error),
    // PARITY: mirrors encoding/json's UnmarshalTypeError message shape; the
    // exact Go text (which embeds Go type names) only ever reaches logs.
    #[error(
        "json: cannot unmarshal {value} into Go struct field Config.{field} of type {type_name}"
    )]
    UnmarshalType {
        value: String,
        field: String,
        type_name: &'static str,
    },
    #[error("json: cannot unmarshal {value} into Go value of type leet.Config")]
    UnmarshalTopLevel { value: String },
    /// Validation failures from setters (`fmt.Errorf` in Go).
    #[error("{0}")]
    Validation(String),
}

/// ConfigManager manages application configuration with automatic
/// persistence to disk.
///
/// All setter methods automatically save changes to disk.
// PARITY: Go guards state with sync.RWMutex (config.go:158) because getters
// are callable from View/Cmd closures. Per CONCURRENCY.md S8 all access is
// on the main thread in the Rust design, so the mutex is dropped and setters
// take `&mut self`; `save()` stays synchronous.
#[derive(Debug)]
pub struct ConfigManager {
    path: PathBuf,
    config: Config,
    pending_grid_config: GridConfigTarget,
}

impl ConfigManager {
    // PARITY: Go takes an *observability.CoreLogger; the Rust port logs via
    // `tracing` at the same call sites, so there is no logger parameter.
    pub fn new(path: impl Into<PathBuf>) -> ConfigManager {
        let mut cm = ConfigManager {
            path: path.into(),
            config: Config::default(),
            pending_grid_config: GridConfigTarget::None,
        };
        if let Err(err) = cm.load_or_create_config() {
            // PARITY: missing space after the colon matches Go
            // (config.go:221).
            tracing::error!("config: error loading or creating:{err}");
        }

        cm
    }

    /// loadOrCreateConfig loads the configuration from disk or stores and
    /// uses defaults.
    fn load_or_create_config(&mut self) -> Result<(), ConfigError> {
        let data = match fs::read(&self.path) {
            // No config file yet, create and save it.
            Err(err) if err.kind() == io::ErrorKind::NotFound => {
                if let Some(dir) = self.path.parent()
                    && !dir.as_os_str().is_empty()
                {
                    // os.MkdirAll(dir, 0o755) (config.go:234).
                    let _ = go_mkdir_all(dir, 0o755);
                }
                return self.save();
            }
            Err(err) => return Err(err.into()),
            Ok(data) => data,
        };

        unmarshal_config(&mut self.config, &data)?;

        self.normalize_config();

        Ok(())
    }

    /// normalizeConfig ensures all config values are within valid ranges.
    fn normalize_config(&mut self) {
        // Clamp grid dimensions
        self.config.metrics_grid.rows =
            clamp(self.config.metrics_grid.rows, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.metrics_grid.cols =
            clamp(self.config.metrics_grid.cols, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.system_grid.rows =
            clamp(self.config.system_grid.rows, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.system_grid.cols =
            clamp(self.config.system_grid.cols, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.media_grid.rows =
            clamp(self.config.media_grid.rows, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.media_grid.cols =
            clamp(self.config.media_grid.cols, MIN_GRID_SIZE, MAX_GRID_SIZE);

        self.config.workspace_metrics_grid.cols = clamp(
            self.config.workspace_metrics_grid.cols,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.workspace_metrics_grid.rows = clamp(
            self.config.workspace_metrics_grid.rows,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.workspace_system_grid.rows = clamp(
            self.config.workspace_system_grid.rows,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.workspace_system_grid.cols = clamp(
            self.config.workspace_system_grid.cols,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.workspace_media_grid.rows = clamp(
            self.config.workspace_media_grid.rows,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.workspace_media_grid.cols = clamp(
            self.config.workspace_media_grid.cols,
            MIN_GRID_SIZE,
            MAX_GRID_SIZE,
        );
        self.config.symon_grid.rows =
            clamp(self.config.symon_grid.rows, MIN_GRID_SIZE, MAX_GRID_SIZE);
        self.config.symon_grid.cols =
            clamp(self.config.symon_grid.cols, MIN_GRID_SIZE, MAX_GRID_SIZE);

        if !is_known_color_scheme(&self.config.color_scheme) {
            self.config.color_scheme = DEFAULT_COLOR_SCHEME.to_string();
        }

        if !is_known_color_scheme(&self.config.per_plot_color_scheme) {
            self.config.per_plot_color_scheme = DEFAULT_PER_PLOT_COLOR_SCHEME.to_string();
        }

        if !is_known_color_scheme(&self.config.system_color_scheme) {
            self.config.system_color_scheme = DEFAULT_SYSTEM_COLOR_SCHEME.to_string();
        }

        if !is_known_color_scheme(&self.config.french_fries_color_scheme) {
            self.config.french_fries_color_scheme = DEFAULT_FRENCH_FRIES_COLOR_SCHEME.to_string();
        }

        if !is_known_color_scheme(&self.config.tag_color_scheme) {
            self.config.tag_color_scheme = DEFAULT_TAG_COLOR_SCHEME.to_string();
        }

        if self.config.system_color_mode != COLOR_MODE_PER_PLOT
            && self.config.system_color_mode != COLOR_MODE_PER_SERIES
        {
            self.config.system_color_mode = DEFAULT_SYSTEM_COLOR_MODE.to_string();
        }

        if self.config.single_run_color_mode != COLOR_MODE_PER_PLOT
            && self.config.single_run_color_mode != COLOR_MODE_PER_SERIES
        {
            self.config.single_run_color_mode = DEFAULT_SINGLE_RUN_COLOR_MODE.to_string();
        }

        if self.config.heartbeat_interval <= 0 {
            self.config.heartbeat_interval = DEFAULT_HEARTBEAT_INTERVAL;
        }

        if self.config.system_tail_window_minutes <= 0 {
            self.config.system_tail_window_minutes = DEFAULT_SYSTEM_TAIL_WINDOW_MINS;
        }

        if self.config.startup_mode != STARTUP_MODE_WORKSPACE_LATEST
            && self.config.startup_mode != STARTUP_MODE_SINGLE_RUN_LATEST
        {
            self.config.startup_mode = DEFAULT_STARTUP_MODE.to_string();
        }
    }

    /// save writes the current configuration to disk.
    fn save(&self) -> Result<(), ConfigError> {
        // json.MarshalIndent(cm.config, "", "  ") — serde_json's pretty
        // printer produces identical bytes for this struct (2-space indent,
        // ": " separators, no trailing newline).
        let data = serde_json::to_string_pretty(&self.config)?;

        let target_path = &self.path;
        let mut tmp = target_path.as_os_str().to_os_string();
        tmp.push(".tmp");
        let temp_path = PathBuf::from(tmp);

        // Write atomically via temp file + rename.
        // os.WriteFile(tempPath, data, 0o644) (config.go:345).
        go_write_file(&temp_path, data.as_bytes(), 0o644).map_err(ConfigError::WriteTemp)?;
        fs::rename(&temp_path, target_path).map_err(ConfigError::Rename)?;

        Ok(())
    }

    /// MetricsGrid returns the metrics grid configuration.
    pub fn metrics_grid(&self) -> (i64, i64) {
        (self.config.metrics_grid.rows, self.config.metrics_grid.cols)
    }

    /// SetMetricsRows sets the metrics grid rows.
    pub fn set_metrics_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.metrics_grid.rows = rows;
        self.save()
    }

    /// SetMetricsCols sets the metrics grid columns.
    pub fn set_metrics_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.metrics_grid.cols = cols;
        self.save()
    }

    /// SystemGrid returns the system grid configuration.
    pub fn system_grid(&self) -> (i64, i64) {
        (self.config.system_grid.rows, self.config.system_grid.cols)
    }

    /// SetSystemRows sets the system grid rows.
    pub fn set_system_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.system_grid.rows = rows;
        self.save()
    }

    /// SetSystemCols sets the system grid columns.
    pub fn set_system_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.system_grid.cols = cols;
        self.save()
    }

    /// MediaGrid returns the media grid configuration.
    pub fn media_grid(&self) -> (i64, i64) {
        (self.config.media_grid.rows, self.config.media_grid.cols)
    }

    /// SetMediaRows sets the media grid rows.
    pub fn set_media_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.media_grid.rows = rows;
        self.save()
    }

    /// SetMediaCols sets the media grid columns.
    pub fn set_media_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.media_grid.cols = cols;
        self.save()
    }

    /// WorkspaceMetricsGrid returns the workspace metrics grid configuration.
    pub fn workspace_metrics_grid(&self) -> (i64, i64) {
        (
            self.config.workspace_metrics_grid.rows,
            self.config.workspace_metrics_grid.cols,
        )
    }

    pub fn set_workspace_metrics_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.workspace_metrics_grid.rows = rows;
        self.save()
    }

    pub fn set_workspace_metrics_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.workspace_metrics_grid.cols = cols;
        self.save()
    }

    /// WorkspaceSystemGrid returns the workspace system grid configuration.
    pub fn workspace_system_grid(&self) -> (i64, i64) {
        (
            self.config.workspace_system_grid.rows,
            self.config.workspace_system_grid.cols,
        )
    }

    /// WorkspaceMediaGrid returns the workspace media grid configuration.
    pub fn workspace_media_grid(&self) -> (i64, i64) {
        (
            self.config.workspace_media_grid.rows,
            self.config.workspace_media_grid.cols,
        )
    }

    /// SymonGrid returns the standalone system monitor grid configuration.
    pub fn symon_grid(&self) -> (i64, i64) {
        (self.config.symon_grid.rows, self.config.symon_grid.cols)
    }

    pub fn set_workspace_system_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.workspace_system_grid.rows = rows;
        self.save()
    }

    pub fn set_workspace_system_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.workspace_system_grid.cols = cols;
        self.save()
    }

    pub fn set_workspace_media_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.workspace_media_grid.rows = rows;
        self.save()
    }

    pub fn set_workspace_media_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.workspace_media_grid.cols = cols;
        self.save()
    }

    pub fn set_symon_rows(&mut self, rows: i64) -> Result<(), ConfigError> {
        validate_rows(rows)?;
        self.config.symon_grid.rows = rows;
        self.save()
    }

    pub fn set_symon_cols(&mut self, cols: i64) -> Result<(), ConfigError> {
        validate_cols(cols)?;
        self.config.symon_grid.cols = cols;
        self.save()
    }

    /// Path returns the on-disk config path.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Snapshot returns a copy of the current config.
    pub fn snapshot(&self) -> Config {
        self.config.clone()
    }

    /// StartupMode returns the configured startup mode.
    pub fn startup_mode(&self) -> &str {
        &self.config.startup_mode
    }

    /// SetStartupMode sets the startup mode and persists it.
    pub fn set_startup_mode(&mut self, mode: &str) -> Result<(), ConfigError> {
        if mode != STARTUP_MODE_WORKSPACE_LATEST && mode != STARTUP_MODE_SINGLE_RUN_LATEST {
            return Err(ConfigError::Validation(format!(
                "startup_mode must be {} or {}, got {}",
                go_quote(STARTUP_MODE_WORKSPACE_LATEST),
                go_quote(STARTUP_MODE_SINGLE_RUN_LATEST),
                go_quote(mode),
            )));
        }
        self.config.startup_mode = mode.to_string();
        self.save()
    }

    /// ColorScheme returns the current color scheme.
    pub fn color_scheme(&self) -> &str {
        &self.config.color_scheme
    }

    pub fn set_color_scheme(&mut self, scheme: &str) -> Result<(), ConfigError> {
        if !is_known_color_scheme(scheme) {
            return Err(unknown_color_scheme(scheme));
        }
        self.config.color_scheme = scheme.to_string();
        self.save()
    }

    pub fn per_plot_color_scheme(&self) -> &str {
        &self.config.per_plot_color_scheme
    }

    pub fn set_per_plot_color_scheme(&mut self, scheme: &str) -> Result<(), ConfigError> {
        if !is_known_color_scheme(scheme) {
            return Err(unknown_color_scheme(scheme));
        }
        self.config.per_plot_color_scheme = scheme.to_string();
        self.save()
    }

    pub fn tag_color_scheme(&self) -> &str {
        &self.config.tag_color_scheme
    }

    pub fn set_tag_color_scheme(&mut self, scheme: &str) -> Result<(), ConfigError> {
        if !is_known_color_scheme(scheme) {
            return Err(unknown_color_scheme(scheme));
        }
        self.config.tag_color_scheme = scheme.to_string();
        self.save()
    }

    pub fn single_run_color_mode(&self) -> &str {
        &self.config.single_run_color_mode
    }

    pub fn set_single_run_color_mode(&mut self, mode: &str) -> Result<(), ConfigError> {
        if mode != COLOR_MODE_PER_PLOT && mode != COLOR_MODE_PER_SERIES {
            return Err(ConfigError::Validation(format!(
                "single_run_color_mode must be {} or {}, got {}",
                go_quote(COLOR_MODE_PER_PLOT),
                go_quote(COLOR_MODE_PER_SERIES),
                go_quote(mode),
            )));
        }
        self.config.single_run_color_mode = mode.to_string();
        self.save()
    }

    /// SystemColorScheme returns the color scheme for system metrics.
    pub fn system_color_scheme(&self) -> &str {
        &self.config.system_color_scheme
    }

    /// FrenchFriesColorScheme returns the color scheme for French Fries
    /// heatmaps.
    pub fn french_fries_color_scheme(&self) -> &str {
        &self.config.french_fries_color_scheme
    }

    /// SystemColorMode returns the color assignment mode for system metrics.
    pub fn system_color_mode(&self) -> &str {
        &self.config.system_color_mode
    }

    /// SetSystemColorScheme sets the system color scheme.
    pub fn set_system_color_scheme(&mut self, scheme: &str) -> Result<(), ConfigError> {
        if !is_known_color_scheme(scheme) {
            return Err(unknown_color_scheme(scheme));
        }

        self.config.system_color_scheme = scheme.to_string();
        self.save()
    }

    /// SetFrenchFriesColorScheme sets the French Fries heatmap color scheme.
    pub fn set_french_fries_color_scheme(&mut self, scheme: &str) -> Result<(), ConfigError> {
        if !is_known_color_scheme(scheme) {
            return Err(unknown_color_scheme(scheme));
        }

        self.config.french_fries_color_scheme = scheme.to_string();
        self.save()
    }

    /// SetSystemColorMode sets the system color mode.
    pub fn set_system_color_mode(&mut self, mode: &str) -> Result<(), ConfigError> {
        if mode != COLOR_MODE_PER_PLOT && mode != COLOR_MODE_PER_SERIES {
            return Err(ConfigError::Validation(format!(
                "invalid color mode: {mode} (must be {COLOR_MODE_PER_PLOT} or {COLOR_MODE_PER_SERIES})"
            )));
        }

        self.config.system_color_mode = mode.to_string();
        self.save()
    }

    /// SystemTailWindow returns the default live tail window for system
    /// charts.
    pub fn system_tail_window(&self) -> Duration {
        // time.Duration(minutes) * time.Minute (config.go:730).
        go_duration_mul(self.config.system_tail_window_minutes, GO_TIME_MINUTE)
    }

    /// SetSystemTailWindowMinutes sets the default live tail window for
    /// system charts.
    pub fn set_system_tail_window_minutes(&mut self, minutes: i64) -> Result<(), ConfigError> {
        if minutes <= 0 {
            return Err(ConfigError::Validation(
                "system tail window must be a positive integer".to_string(),
            ));
        }

        self.config.system_tail_window_minutes = minutes;
        self.save()
    }

    /// HeartbeatInterval returns the heartbeat interval as a Duration.
    pub fn heartbeat_interval(&self) -> Duration {
        // time.Duration(seconds) * time.Second (config.go:750).
        go_duration_mul(self.config.heartbeat_interval, GO_TIME_SECOND)
    }

    /// SetHeartbeatInterval sets the heartbeat interval in seconds.
    pub fn set_heartbeat_interval(&mut self, seconds: i64) -> Result<(), ConfigError> {
        if seconds <= 0 {
            return Err(ConfigError::Validation(
                "heartbeat interval must be a positive integer".to_string(),
            ));
        }

        self.config.heartbeat_interval = seconds;
        self.save()
    }

    /// LeftSidebarVisible returns whether the left sidebar should be visible.
    pub fn left_sidebar_visible(&self) -> bool {
        self.config.left_sidebar_visible
    }

    /// SetLeftSidebarVisible sets the left sidebar visibility.
    pub fn set_left_sidebar_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.left_sidebar_visible = visible;
        self.save()
    }

    /// RightSidebarVisible returns whether the right sidebar should be
    /// visible.
    pub fn right_sidebar_visible(&self) -> bool {
        self.config.right_sidebar_visible
    }

    /// SetRightSidebarVisible sets the right sidebar visibility.
    pub fn set_right_sidebar_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.right_sidebar_visible = visible;
        self.save()
    }

    /// ConsoleLogsVisible returns whether the console logs pane
    /// should be visible in single-run mode.
    pub fn console_logs_visible(&self) -> bool {
        self.config.console_logs_visible
    }

    /// SetConsoleLogsVisible sets the single-run console logs pane
    /// visibility.
    pub fn set_console_logs_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.console_logs_visible = visible;
        self.save()
    }

    /// MetricsGridVisible returns whether the metrics grid should be visible
    /// in single-run mode.
    pub fn metrics_grid_visible(&self) -> bool {
        self.config.metrics_grid_visible
    }

    /// SetMetricsGridVisible sets the single-run metrics grid visibility.
    pub fn set_metrics_grid_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.metrics_grid_visible = visible;
        self.save()
    }

    /// MediaVisible returns whether the media pane should be visible in
    /// single-run mode.
    pub fn media_visible(&self) -> bool {
        self.config.media_visible
    }

    /// SetMediaVisible sets the single-run media pane visibility.
    pub fn set_media_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.media_visible = visible;
        self.save()
    }

    pub fn is_awaiting_grid_config(&self) -> bool {
        self.pending_grid_config != GridConfigTarget::None
    }

    /// SetPendingGridConfig set the pending metrics/system grid configuration
    /// target.
    pub fn set_pending_grid_config(&mut self, gct: GridConfigTarget) {
        self.pending_grid_config = gct;
    }

    /// SetGridConfig sets a value for a pending grid config target (metrics
    /// or system).
    pub fn set_grid_config(&mut self, num: i64) -> Result<String, ConfigError> {
        let pgc = self.pending_grid_config;

        // PARITY: Go builds a map of {setter, label} entries and looks up the
        // pending target (config.go:860-897); a match is the Rust equivalent.
        let (result, label) = match pgc {
            GridConfigTarget::MetricsCols => (self.set_metrics_cols(num), "Metrics grid columns"),
            GridConfigTarget::MetricsRows => (self.set_metrics_rows(num), "Metrics grid rows"),
            GridConfigTarget::SystemCols => (self.set_system_cols(num), "System grid columns"),
            GridConfigTarget::SystemRows => (self.set_system_rows(num), "System grid rows"),
            GridConfigTarget::MediaCols => (self.set_media_cols(num), "Media grid columns"),
            GridConfigTarget::MediaRows => (self.set_media_rows(num), "Media grid rows"),
            GridConfigTarget::WorkspaceMetricsCols => (
                self.set_workspace_metrics_cols(num),
                "Workspace metrics grid columns",
            ),
            GridConfigTarget::WorkspaceMetricsRows => (
                self.set_workspace_metrics_rows(num),
                "Workspace metrics grid rows",
            ),
            GridConfigTarget::WorkspaceSystemCols => (
                self.set_workspace_system_cols(num),
                "Workspace system grid columns",
            ),
            GridConfigTarget::WorkspaceSystemRows => (
                self.set_workspace_system_rows(num),
                "Workspace system grid rows",
            ),
            GridConfigTarget::WorkspaceMediaCols => (
                self.set_workspace_media_cols(num),
                "Workspace media grid columns",
            ),
            GridConfigTarget::WorkspaceMediaRows => (
                self.set_workspace_media_rows(num),
                "Workspace media grid rows",
            ),
            GridConfigTarget::SymonCols => (self.set_symon_cols(num), "Symon grid columns"),
            GridConfigTarget::SymonRows => (self.set_symon_rows(num), "Symon grid rows"),
            GridConfigTarget::None => return Ok(String::new()),
        };

        result?;
        Ok(format!("{label} set to {num}"))
    }

    /// SetConfig replaces the full config (validated) and persists it.
    pub fn set_config(&mut self, cfg: &Config) -> Result<(), ConfigError> {
        self.config = cfg.clone();
        self.normalize_config();
        self.save()
    }

    /// GridConfigStatus returns the status message to display when awaiting
    /// grid config input.
    pub fn grid_config_status(&self) -> &'static str {
        match self.pending_grid_config {
            GridConfigTarget::MetricsCols | GridConfigTarget::WorkspaceMetricsCols => {
                "Press 1-9 to set metrics grid columns (ESC to cancel)"
            }
            GridConfigTarget::MetricsRows | GridConfigTarget::WorkspaceMetricsRows => {
                "Press 1-9 to set metrics grid rows (ESC to cancel)"
            }
            GridConfigTarget::SystemCols
            | GridConfigTarget::WorkspaceSystemCols
            | GridConfigTarget::SymonCols => "Press 1-9 to set system grid columns (ESC to cancel)",
            GridConfigTarget::SystemRows
            | GridConfigTarget::WorkspaceSystemRows
            | GridConfigTarget::SymonRows => "Press 1-9 to set system grid rows (ESC to cancel)",
            GridConfigTarget::MediaCols | GridConfigTarget::WorkspaceMediaCols => {
                "Press 1-9 to set media grid columns (ESC to cancel)"
            }
            GridConfigTarget::MediaRows | GridConfigTarget::WorkspaceMediaRows => {
                "Press 1-9 to set media grid rows (ESC to cancel)"
            }
            GridConfigTarget::None => "",
        }
    }

    /// WorkspaceOverviewVisible returns whether the overview sidebar should
    /// be visible in workspace mode.
    pub fn workspace_overview_visible(&self) -> bool {
        self.config.workspace_overview_visible
    }

    /// SetWorkspaceOverviewVisible sets the workspace overview sidebar
    /// visibility.
    pub fn set_workspace_overview_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.workspace_overview_visible = visible;
        self.save()
    }

    /// WorkspaceSystemMetricsVisible returns whether the system metrics pane
    /// should be visible in workspace mode.
    pub fn workspace_system_metrics_visible(&self) -> bool {
        self.config.workspace_system_metrics_visible
    }

    /// SetWorkspaceSystemMetricsVisible sets the workspace system metrics
    /// pane visibility.
    pub fn set_workspace_system_metrics_visible(
        &mut self,
        visible: bool,
    ) -> Result<(), ConfigError> {
        self.config.workspace_system_metrics_visible = visible;
        self.save()
    }

    /// WorkspaceConsoleLogsVisible returns whether the console logs pane
    /// should be visible in workspace mode.
    pub fn workspace_console_logs_visible(&self) -> bool {
        self.config.workspace_console_logs_visible
    }

    /// SetWorkspaceConsoleLogsVisible sets the workspace console logs pane
    /// visibility.
    pub fn set_workspace_console_logs_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.workspace_console_logs_visible = visible;
        self.save()
    }

    /// WorkspaceMetricsGridVisible returns whether the metrics grid should be
    /// visible in workspace mode.
    pub fn workspace_metrics_grid_visible(&self) -> bool {
        self.config.workspace_metrics_grid_visible
    }

    /// SetWorkspaceMetricsGridVisible sets the workspace metrics grid
    /// visibility.
    pub fn set_workspace_metrics_grid_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.workspace_metrics_grid_visible = visible;
        self.save()
    }

    /// WorkspaceMediaVisible returns whether the media pane should be visible
    /// in workspace mode.
    pub fn workspace_media_visible(&self) -> bool {
        self.config.workspace_media_visible
    }

    /// SetWorkspaceMediaVisible sets the workspace media pane visibility.
    pub fn set_workspace_media_visible(&mut self, visible: bool) -> Result<(), ConfigError> {
        self.config.workspace_media_visible = visible;
        self.save()
    }
}

fn clamp(val: i64, minimum: i64, maximum: i64) -> i64 {
    if val < minimum {
        return minimum;
    }
    if val > maximum {
        return maximum;
    }
    val
}

/// Go `time.Second` / `time.Minute` in `time.Duration` (i64) nanoseconds.
const GO_TIME_SECOND: i64 = 1_000_000_000;
const GO_TIME_MINUTE: i64 = 60 * GO_TIME_SECOND;

/// `time.Duration(n) * unit` — Go duration math on i64 nanoseconds.
// PARITY: Go's time.Duration is a signed 64-bit nanosecond count and Go
// integer multiplication wraps silently on overflow; a bare Rust `*` would
// panic in debug builds instead. Out-of-range values are reachable here when
// a config-file type error makes loadOrCreateConfig return before
// normalizeConfig runs (config.go:242-248), leaving e.g. a negative minutes
// value in place. std::time::Duration cannot represent Go's negative
// results, so those clamp to Duration::ZERO (divergence; Go returns a
// negative Duration).
fn go_duration_mul(n: i64, unit: i64) -> Duration {
    let nanos = n.wrapping_mul(unit);
    if nanos < 0 {
        Duration::ZERO
    } else {
        Duration::from_nanos(nanos as u64)
    }
}

/// os.MkdirAll(dir, perm): every directory created gets `perm` (pre-umask);
/// std's `create_dir_all` would use 0o777.
fn go_mkdir_all(dir: &Path, mode: u32) -> io::Result<()> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    builder.mode(mode);
    #[cfg(not(unix))]
    let _ = mode;
    builder.create(dir)
}

/// os.WriteFile(name, data, perm): O_WRONLY|O_CREATE|O_TRUNC with `perm`
/// applied (pre-umask) only when the file is created; std's `fs::write`
/// would create with 0o666.
// PARITY: Go also surfaces the f.Close() error; std ignores close errors on
// drop (write errors are still surfaced).
fn go_write_file(path: &Path, data: &[u8], mode: u32) -> io::Result<()> {
    use std::io::Write;

    let mut opts = fs::OpenOptions::new();
    opts.write(true).create(true).truncate(true);
    #[cfg(unix)]
    opts.mode(mode);
    #[cfg(not(unix))]
    let _ = mode;
    let mut f = opts.open(path)?;
    f.write_all(data)
}

fn validate_rows(rows: i64) -> Result<(), ConfigError> {
    if !(MIN_GRID_SIZE..=MAX_GRID_SIZE).contains(&rows) {
        return Err(ConfigError::Validation(format!(
            "rows must be between {MIN_GRID_SIZE} and {MAX_GRID_SIZE}, got {rows}"
        )));
    }
    Ok(())
}

fn validate_cols(cols: i64) -> Result<(), ConfigError> {
    if !(MIN_GRID_SIZE..=MAX_GRID_SIZE).contains(&cols) {
        return Err(ConfigError::Validation(format!(
            "cols must be between {MIN_GRID_SIZE} and {MAX_GRID_SIZE}, got {cols}"
        )));
    }
    Ok(())
}

fn unknown_color_scheme(scheme: &str) -> ConfigError {
    ConfigError::Validation(format!("unknown color scheme: {}", go_quote(scheme)))
}

/// Go `%q` (strconv.Quote) for the strings that reach config error messages.
// PARITY: strconv.Quote also escapes non-printable Unicode with \u forms;
// scheme/mode names are plain ASCII so only the standard escapes are needed.
fn go_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x07' => out.push_str("\\a"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\x0b' => out.push_str("\\v"),
            c if (c as u32) < 0x20 || c == '\x7f' => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

// --- JSON unmarshal (Go encoding/json semantics for Config) ---------------
//
// Go's `json.Unmarshal(data, &cm.config)` merges into the pre-populated
// default struct: unknown JSON fields are ignored, missing fields keep their
// defaults (including partially-specified GridConfig objects), `null` is a
// no-op, and a type mismatch skips the field, completes the rest, and
// reports an error. serde derive cannot express instance-relative defaults
// for nested structs, so the merge is hand-rolled.

/// json.Unmarshal(data, &config) for [`Config`].
fn unmarshal_config(config: &mut Config, data: &[u8]) -> Result<(), ConfigError> {
    let value: Value = serde_json::from_slice(data)?;
    merge_config_value(config, &value)
}

fn merge_config_value(config: &mut Config, value: &Value) -> Result<(), ConfigError> {
    let obj = match value {
        // PARITY: unmarshaling JSON null into a struct is a no-op in Go.
        Value::Null => return Ok(()),
        Value::Object(obj) => obj,
        other => {
            return Err(ConfigError::UnmarshalTopLevel {
                value: json_value_kind(other),
            });
        }
    };

    // PARITY: encoding/json reports the earliest type error in *document*
    // order; here the first error in struct declaration order is reported.
    // Either way the config ends up partially applied and the caller
    // (loadOrCreateConfig) returns before normalizeConfig runs.
    let mut first_err: Option<ConfigError> = None;

    merge_string(
        &mut config.startup_mode,
        obj,
        "startup_mode",
        &mut first_err,
    );
    merge_grid(
        &mut config.metrics_grid,
        obj,
        "metrics_grid",
        &mut first_err,
    );
    merge_grid(&mut config.system_grid, obj, "system_grid", &mut first_err);
    merge_grid(&mut config.media_grid, obj, "media_grid", &mut first_err);
    merge_grid(
        &mut config.workspace_metrics_grid,
        obj,
        "workspace_metrics_grid",
        &mut first_err,
    );
    merge_grid(
        &mut config.workspace_system_grid,
        obj,
        "workspace_system_grid",
        &mut first_err,
    );
    merge_grid(
        &mut config.workspace_media_grid,
        obj,
        "workspace_media_grid",
        &mut first_err,
    );
    merge_grid(&mut config.symon_grid, obj, "symon_grid", &mut first_err);
    merge_string(
        &mut config.color_scheme,
        obj,
        "color_scheme",
        &mut first_err,
    );
    merge_string(
        &mut config.tag_color_scheme,
        obj,
        "tag_color_scheme",
        &mut first_err,
    );
    merge_string(
        &mut config.per_plot_color_scheme,
        obj,
        "per_plot_color_scheme",
        &mut first_err,
    );
    merge_string(
        &mut config.system_color_scheme,
        obj,
        "system_color_scheme",
        &mut first_err,
    );
    merge_string(
        &mut config.french_fries_color_scheme,
        obj,
        "french_fries_color_scheme",
        &mut first_err,
    );
    merge_string(
        &mut config.system_color_mode,
        obj,
        "system_color_mode",
        &mut first_err,
    );
    merge_i64(
        &mut config.system_tail_window_minutes,
        obj,
        "system_tail_window_minutes",
        "system_tail_window_minutes",
        &mut first_err,
    );
    merge_string(
        &mut config.single_run_color_mode,
        obj,
        "single_run_color_mode",
        &mut first_err,
    );
    merge_i64(
        &mut config.heartbeat_interval,
        obj,
        "heartbeat_interval_seconds",
        "heartbeat_interval_seconds",
        &mut first_err,
    );
    merge_bool(
        &mut config.left_sidebar_visible,
        obj,
        "left_sidebar_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.right_sidebar_visible,
        obj,
        "right_sidebar_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.metrics_grid_visible,
        obj,
        "metrics_grid_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.console_logs_visible,
        obj,
        "console_logs_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.media_visible,
        obj,
        "media_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.workspace_overview_visible,
        obj,
        "workspace_overview_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.workspace_metrics_grid_visible,
        obj,
        "workspace_metrics_grid_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.workspace_system_metrics_visible,
        obj,
        "workspace_system_metrics_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.workspace_console_logs_visible,
        obj,
        "workspace_console_logs_visible",
        &mut first_err,
    );
    merge_bool(
        &mut config.workspace_media_visible,
        obj,
        "workspace_media_visible",
        &mut first_err,
    );

    match first_err {
        Some(err) => Err(err),
        None => Ok(()),
    }
}

/// Field lookup mirroring encoding/json key matching: an exact match is
/// preferred, otherwise a case-insensitive one is accepted.
// PARITY: with duplicate case-insensitive keys Go's last-in-document-order
// wins; here the first case-insensitive match in map order wins. The file is
// machine-written with exact keys, so this only differs on hand-edits.
fn lookup_field<'a>(obj: &'a serde_json::Map<String, Value>, key: &str) -> Option<&'a Value> {
    if let Some(v) = obj.get(key) {
        return Some(v);
    }
    obj.iter()
        .find(|(k, _)| k.eq_ignore_ascii_case(key))
        .map(|(_, v)| v)
}

fn record_err(slot: &mut Option<ConfigError>, err: ConfigError) {
    if slot.is_none() {
        *slot = Some(err);
    }
}

/// The value description encoding/json puts in UnmarshalTypeError.Value.
fn json_value_kind(v: &Value) -> String {
    match v {
        Value::Null => "null".to_string(),
        Value::Bool(_) => "bool".to_string(),
        // Go includes the offending literal for numbers.
        Value::Number(n) => format!("number {n}"),
        Value::String(_) => "string".to_string(),
        Value::Array(_) => "array".to_string(),
        Value::Object(_) => "object".to_string(),
    }
}

fn merge_string(
    dst: &mut String,
    obj: &serde_json::Map<String, Value>,
    key: &str,
    first_err: &mut Option<ConfigError>,
) {
    let Some(v) = lookup_field(obj, key) else {
        return;
    };
    match v {
        Value::Null => {}
        Value::String(s) => *dst = s.clone(),
        other => record_err(
            first_err,
            ConfigError::UnmarshalType {
                value: json_value_kind(other),
                field: key.to_string(),
                type_name: "string",
            },
        ),
    }
}

fn merge_i64(
    dst: &mut i64,
    obj: &serde_json::Map<String, Value>,
    key: &str,
    field_path: &str,
    first_err: &mut Option<ConfigError>,
) {
    let Some(v) = lookup_field(obj, key) else {
        return;
    };
    match v {
        Value::Null => {}
        Value::Number(n) => match n.as_i64() {
            // PARITY: Go rejects fractional/exponent literals and overflow
            // when decoding into int; serde_json's as_i64 does the same.
            Some(x) => *dst = x,
            None => record_err(
                first_err,
                ConfigError::UnmarshalType {
                    value: json_value_kind(v),
                    field: field_path.to_string(),
                    type_name: "int",
                },
            ),
        },
        other => record_err(
            first_err,
            ConfigError::UnmarshalType {
                value: json_value_kind(other),
                field: field_path.to_string(),
                type_name: "int",
            },
        ),
    }
}

fn merge_bool(
    dst: &mut bool,
    obj: &serde_json::Map<String, Value>,
    key: &str,
    first_err: &mut Option<ConfigError>,
) {
    let Some(v) = lookup_field(obj, key) else {
        return;
    };
    match v {
        Value::Null => {}
        Value::Bool(b) => *dst = *b,
        other => record_err(
            first_err,
            ConfigError::UnmarshalType {
                value: json_value_kind(other),
                field: key.to_string(),
                type_name: "bool",
            },
        ),
    }
}

fn merge_grid(
    dst: &mut GridConfig,
    obj: &serde_json::Map<String, Value>,
    key: &str,
    first_err: &mut Option<ConfigError>,
) {
    let Some(v) = lookup_field(obj, key) else {
        return;
    };
    match v {
        Value::Null => {}
        Value::Object(m) => {
            // A partially-specified grid keeps the default for the missing
            // dimension (Go merges into the pre-populated struct).
            merge_i64(&mut dst.rows, m, "rows", &format!("{key}.rows"), first_err);
            merge_i64(&mut dst.cols, m, "cols", &format!("{key}.cols"), first_err);
        }
        other => record_err(
            first_err,
            ConfigError::UnmarshalType {
                value: json_value_kind(other),
                field: key.to_string(),
                type_name: "leet.GridConfig",
            },
        ),
    }
}

// --- Config path resolution ------------------------------------------------

/// leetConfigPath returns the path where the config should be stored.
///
/// Matches the Python logic (same directory as the system "settings" file),
/// with fallbacks to UserConfigDir and a temp dir.
pub fn leet_config_path() -> PathBuf {
    // 1) Honor WANDB_CONFIG_DIR (like in Python)
    let raw = env::var(ENV_CONFIG_DIR).unwrap_or_default();
    let raw = raw.trim();
    if !raw.is_empty()
        && let Some(p) = config_path_from_dir(raw)
    {
        return p;
    }

    // 2) Default to ~/.config/wandb (like in Python)
    if let Some(home) = user_home_dir()
        && let Some(p) = config_path_from_dir(&go_path_join(&home, ".config/wandb"))
    {
        return p;
    }

    // 3) Fallback: OS user config dir (/wandb)
    if let Some(base) = user_config_dir()
        && let Some(p) = config_path_from_dir(&go_path_join(&base, "wandb"))
    {
        return p;
    }

    // 4) Last resort: a fresh temp dir
    if let Some(tmp) = mkdir_temp_wandb_leet() {
        return tmp.join(LEET_CONFIG_NAME);
    }

    // Extremely unlikely final fallback
    env::temp_dir().join(LEET_CONFIG_NAME)
}

fn config_path_from_dir(dir: &str) -> Option<PathBuf> {
    let d = expand_and_clean(dir);
    if ensure_writable_dir(&d).is_err() {
        return None;
    }
    Some(PathBuf::from(go_path_join(&d, LEET_CONFIG_NAME)))
}

fn expand_and_clean(p: &str) -> String {
    let mut p = p.trim().to_string();
    if p.is_empty() {
        return p;
    }
    if p.starts_with('~')
        && let Some(home) = user_home_dir()
    {
        if p.len() == 1 {
            p = home;
        } else {
            let b = p.as_bytes()[1];
            if b == b'/' || b == b'\\' {
                p = go_path_join(&home, &p[2..]);
            }
        }
    }
    if let Some(abs) = abs_path(&p) {
        p = abs;
    }
    clean_path(&p)
}

/// ensureWritableDir verifies directory writability without leaving files
/// behind.
fn ensure_writable_dir(dir: &str) -> io::Result<()> {
    if dir.is_empty() {
        return Err(io::Error::other("empty dir"));
    }
    // os.MkdirAll(dir, 0o755) (config.go:1084).
    go_mkdir_all(Path::new(dir), 0o755)?;
    // os.CreateTemp(dir, ".wandb-leet-writecheck-*") — no tempfile dep in
    // shipped code, so the random suffix + create_new retry loop is inlined.
    // os.CreateTemp opens O_RDWR|O_CREATE|O_EXCL with mode 0o600.
    let mut opts = fs::OpenOptions::new();
    opts.read(true).write(true).create_new(true);
    #[cfg(unix)]
    opts.mode(0o600);
    for attempt in 0..10000u32 {
        let name = format!(
            ".wandb-leet-writecheck-{}",
            temp_rand().wrapping_add(attempt as u64)
        );
        let path = Path::new(dir).join(name);
        match opts.open(&path) {
            Ok(f) => {
                drop(f);
                let _ = fs::remove_file(&path);
                return Ok(());
            }
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(err) => return Err(err),
        }
    }
    Err(io::Error::other("could not create writecheck file"))
}

/// os.MkdirTemp("", "wandb-leet-*"): the directory is created with mode
/// 0o700 (pre-umask).
fn mkdir_temp_wandb_leet() -> Option<PathBuf> {
    let base = env::temp_dir();
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    builder.mode(0o700);
    for attempt in 0..10000u32 {
        let path = base.join(format!(
            "wandb-leet-{}",
            temp_rand().wrapping_add(attempt as u64)
        ));
        match builder.create(&path) {
            Ok(()) => return Some(path),
            Err(err) if err.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(_) => return None,
        }
    }
    None
}

/// A cheap pseudo-random value for temp-name generation (mirrors the role of
/// runtime randomness in os.CreateTemp/os.MkdirTemp).
fn temp_rand() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos() as u64 ^ d.as_secs())
        .unwrap_or(0);
    nanos ^ (u64::from(std::process::id()) << 32)
}

/// os.UserHomeDir for Unix-likes: $HOME, error if unset/empty.
fn user_home_dir() -> Option<String> {
    match env::var("HOME") {
        Ok(home) if !home.is_empty() => Some(home),
        _ => None,
    }
}

/// os.UserConfigDir, mirroring Go's macOS/Linux logic.
fn user_config_dir() -> Option<String> {
    if cfg!(target_os = "macos") {
        // darwin: $HOME/Library/Application Support
        let home = user_home_dir()?;
        Some(home + "/Library/Application Support")
    } else {
        // unix: $XDG_CONFIG_HOME (must be absolute), else $HOME/.config
        let dir = env::var("XDG_CONFIG_HOME").unwrap_or_default();
        if dir.is_empty() {
            let home = user_home_dir()?;
            Some(home + "/.config")
        } else if !dir.starts_with('/') {
            // Go: "path in $XDG_CONFIG_HOME is relative" error.
            None
        } else {
            Some(dir)
        }
    }
}

/// filepath.Join for Unix paths: joins non-empty elements and Cleans.
fn go_path_join(a: &str, b: &str) -> String {
    if a.is_empty() {
        return clean_path(b);
    }
    if b.is_empty() {
        return clean_path(a);
    }
    clean_path(&format!("{a}/{b}"))
}

/// filepath.Abs for Unix paths: Clean if absolute, else Clean(cwd + path).
fn abs_path(p: &str) -> Option<String> {
    if p.starts_with('/') {
        return Some(clean_path(p));
    }
    let cwd = env::current_dir().ok()?;
    Some(clean_path(&format!("{}/{}", cwd.to_string_lossy(), p)))
}

/// filepath.Clean for Unix paths (lexical processing of ".", ".." and
/// repeated separators; empty input yields ".").
fn clean_path(path: &str) -> String {
    if path.is_empty() {
        return ".".to_string();
    }
    let rooted = path.starts_with('/');
    let mut out: Vec<&str> = Vec::new();
    for comp in path.split('/') {
        match comp {
            "" | "." => {}
            ".." => {
                if matches!(out.last(), Some(&last) if last != "..") {
                    out.pop();
                } else if !rooted {
                    out.push("..");
                }
                // rooted: ".." at the root is dropped.
            }
            c => out.push(c),
        }
    }
    let mut s = if rooted {
        "/".to_string()
    } else {
        String::new()
    };
    s.push_str(&out.join("/"));
    if s.is_empty() { ".".to_string() } else { s }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    /// json.MarshalIndent output of the default Go Config, captured from the
    /// Go implementation (1150 bytes, no trailing newline). Pins both the
    /// key order and the byte-level formatting of `save()`.
    const GO_DEFAULT_CONFIG_JSON: &str = r#"{
  "startup_mode": "workspace_latest",
  "metrics_grid": {
    "rows": 4,
    "cols": 3
  },
  "system_grid": {
    "rows": 6,
    "cols": 2
  },
  "media_grid": {
    "rows": 1,
    "cols": 2
  },
  "workspace_metrics_grid": {
    "rows": 3,
    "cols": 3
  },
  "workspace_system_grid": {
    "rows": 3,
    "cols": 3
  },
  "workspace_media_grid": {
    "rows": 1,
    "cols": 2
  },
  "symon_grid": {
    "rows": 3,
    "cols": 3
  },
  "color_scheme": "wandb-vibe-10",
  "tag_color_scheme": "wandb-vibe-10",
  "per_plot_color_scheme": "sunset-glow",
  "system_color_scheme": "wandb-vibe-10",
  "french_fries_color_scheme": "viridis",
  "system_color_mode": "per_series",
  "system_tail_window_minutes": 10,
  "single_run_color_mode": "per_series",
  "heartbeat_interval_seconds": 15,
  "left_sidebar_visible": true,
  "right_sidebar_visible": true,
  "metrics_grid_visible": true,
  "console_logs_visible": false,
  "media_visible": false,
  "workspace_overview_visible": true,
  "workspace_metrics_grid_visible": true,
  "workspace_system_metrics_visible": false,
  "workspace_console_logs_visible": false,
  "workspace_media_visible": false
}"#;

    fn temp_config_path(dir: &tempfile::TempDir) -> PathBuf {
        dir.path().join("config.json")
    }

    // PARITY: the Go test drives the 'r'/'c' + digit hotkeys through the
    // leet.Run tea.Model (leet-tui, Phase 5). The ConfigManager side of that
    // flow — pending-target selection and SetGridConfig — is exercised here;
    // the key routing itself is covered by the leet-tui port.
    #[test]
    fn test_config_hotkeys_update_grid_dimensions() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = ConfigManager::new(temp_config_path(&dir));

        // metrics rows: 'r' then '5' (default focus = metrics grid)
        cfg.set_pending_grid_config(GridConfigTarget::MetricsRows);
        assert_eq!(
            cfg.set_grid_config(5).unwrap(),
            "Metrics grid rows set to 5"
        );
        let (grid_rows, _) = cfg.metrics_grid();
        assert_eq!(grid_rows, 5);

        // metrics cols: 'c' then '4'
        cfg.set_pending_grid_config(GridConfigTarget::MetricsCols);
        assert_eq!(
            cfg.set_grid_config(4).unwrap(),
            "Metrics grid columns set to 4"
        );
        let (_, grid_cols) = cfg.metrics_grid();
        assert_eq!(grid_cols, 4);

        // Focus system metrics, then use universal 'r'/'c' to configure
        // system grid.

        // system rows: 'r' then '2'
        cfg.set_pending_grid_config(GridConfigTarget::SystemRows);
        assert_eq!(cfg.set_grid_config(2).unwrap(), "System grid rows set to 2");
        let (grid_rows, _) = cfg.system_grid();
        assert_eq!(grid_rows, 2);

        // system cols: 'c' then '3'
        cfg.set_pending_grid_config(GridConfigTarget::SystemCols);
        assert_eq!(
            cfg.set_grid_config(3).unwrap(),
            "System grid columns set to 3"
        );
        let (_, grid_cols) = cfg.system_grid();
        assert_eq!(grid_cols, 3);
    }

    #[test]
    fn test_config_set_left_sidebar_visible_toggles_and_persists() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = ConfigManager::new(temp_config_path(&dir));

        // Toggle on
        cfg.set_left_sidebar_visible(true).unwrap();
        assert!(cfg.left_sidebar_visible());

        // Toggle off
        cfg.set_left_sidebar_visible(false).unwrap();
        assert!(!cfg.left_sidebar_visible());
    }

    // PARITY: the Go test asserts the leet.Run model picks the value up on
    // startup (leet-tui, Phase 5); the data-layer contract — the value
    // persists and a fresh manager reads it back — is asserted here.
    #[test]
    fn test_config_set_left_sidebar_visible_affects_model_on_startup() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        let mut cfg = ConfigManager::new(&path);
        cfg.set_left_sidebar_visible(true).unwrap();

        let cfg2 = ConfigManager::new(&path);
        assert!(cfg2.left_sidebar_visible());
    }

    #[test]
    fn test_config_set_tag_color_scheme_persists() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        let mut cfg = ConfigManager::new(&path);

        assert_eq!(cfg.snapshot().tag_color_scheme, DEFAULT_TAG_COLOR_SCHEME);

        cfg.set_tag_color_scheme("bootstrap-vibe").unwrap();
        assert_eq!(cfg.tag_color_scheme(), "bootstrap-vibe");

        let cfg2 = ConfigManager::new(&path);
        assert_eq!(cfg2.snapshot().tag_color_scheme, "bootstrap-vibe");
    }

    #[test]
    fn test_config_set_symon_grid_persists() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        let mut cfg = ConfigManager::new(&path);

        assert_eq!(cfg.snapshot().symon_grid.rows, DEFAULT_SYMON_GRID_ROWS);
        assert_eq!(cfg.snapshot().symon_grid.cols, DEFAULT_SYMON_GRID_COLS);

        cfg.set_symon_rows(4).unwrap();
        cfg.set_symon_cols(2).unwrap();

        let cfg2 = ConfigManager::new(&path);
        let (rows, cols) = cfg2.symon_grid();
        assert_eq!(rows, 4);
        assert_eq!(cols, 2);
    }

    #[test]
    fn test_config_set_french_fries_color_scheme_persists() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        let mut cfg = ConfigManager::new(&path);

        assert_eq!(
            cfg.snapshot().french_fries_color_scheme,
            DEFAULT_FRENCH_FRIES_COLOR_SCHEME
        );

        cfg.set_french_fries_color_scheme("cividis").unwrap();
        assert_eq!(cfg.french_fries_color_scheme(), "cividis");

        let cfg2 = ConfigManager::new(&path);
        assert_eq!(cfg2.snapshot().french_fries_color_scheme, "cividis");
    }

    /// A fresh ConfigManager writes byte-identical output to Go's
    /// json.MarshalIndent (cross-compat: the file is shared with the Go
    /// binary).
    #[test]
    fn test_save_matches_go_marshal_indent_bytes() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        let _cfg = ConfigManager::new(&path);

        let written = fs::read_to_string(&path).unwrap();
        assert_eq!(written, GO_DEFAULT_CONFIG_JSON);
        assert_eq!(written.len(), 1150); // captured from Go
    }

    /// Round-trip a Go-shaped config file: unknown fields are tolerated,
    /// partially-specified grids keep defaults for missing dimensions, and
    /// unknown scheme names normalize to defaults — the exact semantics
    /// observed from the Go implementation for this input:
    ///   system_grid=5,2 color="wandb-vibe-10" hb=42 metrics=4,3
    #[test]
    fn test_config_round_trip_go_shaped_json() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        fs::write(
            &path,
            r#"{
  "system_grid": {"rows": 5},
  "color_scheme": "not-a-scheme",
  "unknown_field": {"x": 1},
  "heartbeat_interval_seconds": 42
}"#,
        )
        .unwrap();

        let cfg = ConfigManager::new(&path);
        let snap = cfg.snapshot();
        assert_eq!(cfg.system_grid(), (5, 2));
        assert_eq!(snap.color_scheme, "wandb-vibe-10");
        assert_eq!(snap.heartbeat_interval, 42);
        assert_eq!(cfg.metrics_grid(), (4, 3));

        // Write back (any setter persists the whole config) and re-read:
        // semantics survive the round trip.
        let mut cfg = cfg;
        cfg.set_left_sidebar_visible(true).unwrap();
        let cfg2 = ConfigManager::new(&path);
        assert_eq!(cfg2.snapshot(), cfg.snapshot());
    }

    /// Loading the full Go-written default file reproduces the defaults and
    /// a subsequent save leaves the bytes unchanged.
    #[test]
    fn test_config_reads_go_written_file_unchanged() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        fs::write(&path, GO_DEFAULT_CONFIG_JSON).unwrap();

        let mut cfg = ConfigManager::new(&path);
        assert_eq!(cfg.snapshot(), Config::default());

        cfg.set_config(&cfg.snapshot()).unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), GO_DEFAULT_CONFIG_JSON);
    }

    /// normalizeConfig clamps grids and resets invalid enum/int values.
    #[test]
    fn test_config_normalize_out_of_range_values() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);
        fs::write(
            &path,
            r#"{
  "startup_mode": "bogus",
  "metrics_grid": {"rows": 0, "cols": 42},
  "system_color_mode": "sideways",
  "heartbeat_interval_seconds": -3,
  "system_tail_window_minutes": 0
}"#,
        )
        .unwrap();

        let cfg = ConfigManager::new(&path);
        let snap = cfg.snapshot();
        assert_eq!(cfg.metrics_grid(), (MIN_GRID_SIZE, MAX_GRID_SIZE));
        assert_eq!(snap.startup_mode, DEFAULT_STARTUP_MODE);
        assert_eq!(snap.system_color_mode, DEFAULT_SYSTEM_COLOR_MODE);
        assert_eq!(snap.heartbeat_interval, DEFAULT_HEARTBEAT_INTERVAL);
        assert_eq!(
            snap.system_tail_window_minutes,
            DEFAULT_SYSTEM_TAIL_WINDOW_MINS
        );
    }

    /// Setter validation preserves Go's error message text.
    #[test]
    fn test_setter_validation_messages() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = ConfigManager::new(temp_config_path(&dir));

        assert_eq!(
            cfg.set_metrics_rows(0).unwrap_err().to_string(),
            "rows must be between 1 and 9, got 0"
        );
        assert_eq!(
            cfg.set_metrics_cols(10).unwrap_err().to_string(),
            "cols must be between 1 and 9, got 10"
        );
        assert_eq!(
            cfg.set_startup_mode("bogus").unwrap_err().to_string(),
            "startup_mode must be \"workspace_latest\" or \"single_run_latest\", got \"bogus\""
        );
        assert_eq!(
            cfg.set_color_scheme("nope").unwrap_err().to_string(),
            "unknown color scheme: \"nope\""
        );
        assert_eq!(
            cfg.set_single_run_color_mode("x").unwrap_err().to_string(),
            "single_run_color_mode must be \"per_plot\" or \"per_series\", got \"x\""
        );
        assert_eq!(
            cfg.set_system_color_mode("x").unwrap_err().to_string(),
            "invalid color mode: x (must be per_plot or per_series)"
        );
        assert_eq!(
            cfg.set_system_tail_window_minutes(0)
                .unwrap_err()
                .to_string(),
            "system tail window must be a positive integer"
        );
        assert_eq!(
            cfg.set_heartbeat_interval(-1).unwrap_err().to_string(),
            "heartbeat interval must be a positive integer"
        );
    }

    /// The config-editor metadata table matches the Go struct: 27 Config
    /// fields in declaration order plus the two GridConfig leaves.
    #[test]
    fn test_config_field_descriptor_table() {
        assert_eq!(CONFIG_FIELDS.len(), 27);
        assert_eq!(GRID_CONFIG_FIELDS.len(), 2);

        // Declaration order matches the serialized key order (the golden Go
        // bytes are the order oracle; serde_json::to_value would lose order).
        let keys: Vec<&str> = GO_DEFAULT_CONFIG_JSON
            .lines()
            .filter_map(|line| line.strip_prefix("  \""))
            .filter_map(|rest| rest.split('"').next())
            .collect();
        let descriptor_keys: Vec<&str> = CONFIG_FIELDS.iter().map(|f| f.json_name).collect();
        assert_eq!(descriptor_keys, keys);

        // Spot-check tag metadata.
        let hb = CONFIG_FIELDS
            .iter()
            .find(|f| f.json_name == "heartbeat_interval_seconds")
            .unwrap();
        assert_eq!(hb.kind, ConfigFieldKind::Int);
        assert_eq!(hb.label, "Heartbeat interval (sec)");
        assert_eq!(hb.desc, "Polling heartbeat for live runs.");
        assert_eq!(hb.min, Some(1));
        assert_eq!(hb.max, None);

        let sm = &CONFIG_FIELDS[0];
        assert_eq!(sm.json_name, "startup_mode");
        assert_eq!(sm.options, "startupModes");

        assert_eq!(GRID_CONFIG_FIELDS[0].json_name, "rows");
        assert_eq!(GRID_CONFIG_FIELDS[0].min, Some(1));
        assert_eq!(GRID_CONFIG_FIELDS[0].max, Some(9));
        assert_eq!(GRID_CONFIG_FIELDS[1].json_name, "cols");
    }

    /// clean_path mirrors Go's filepath.Clean for the Unix cases the config
    /// path resolution can hit.
    #[test]
    fn test_clean_path_matches_go_filepath_clean() {
        assert_eq!(clean_path(""), ".");
        assert_eq!(clean_path("/"), "/");
        assert_eq!(clean_path("/a/b/../c"), "/a/c");
        assert_eq!(clean_path("/a//b///c/"), "/a/b/c");
        assert_eq!(clean_path("/../a"), "/a");
        assert_eq!(clean_path("a/.."), ".");
        assert_eq!(clean_path("../../a"), "../../a");
        assert_eq!(clean_path("./a/./b"), "a/b");
        assert_eq!(clean_path("/a/b/.."), "/a");
    }

    /// grid_config_status covers every pending target with the Go strings.
    #[test]
    fn test_grid_config_status_messages() {
        let dir = tempfile::tempdir().unwrap();
        let mut cfg = ConfigManager::new(temp_config_path(&dir));

        assert!(!cfg.is_awaiting_grid_config());
        assert_eq!(cfg.grid_config_status(), "");

        for (target, want) in [
            (
                GridConfigTarget::MetricsCols,
                "Press 1-9 to set metrics grid columns (ESC to cancel)",
            ),
            (
                GridConfigTarget::WorkspaceMetricsRows,
                "Press 1-9 to set metrics grid rows (ESC to cancel)",
            ),
            (
                GridConfigTarget::SymonCols,
                "Press 1-9 to set system grid columns (ESC to cancel)",
            ),
            (
                GridConfigTarget::WorkspaceSystemRows,
                "Press 1-9 to set system grid rows (ESC to cancel)",
            ),
            (
                GridConfigTarget::MediaCols,
                "Press 1-9 to set media grid columns (ESC to cancel)",
            ),
            (
                GridConfigTarget::WorkspaceMediaRows,
                "Press 1-9 to set media grid rows (ESC to cancel)",
            ),
        ] {
            cfg.set_pending_grid_config(target);
            assert!(cfg.is_awaiting_grid_config());
            assert_eq!(cfg.grid_config_status(), want);
        }

        // SetGridConfig with no pending target returns ("", nil) in Go.
        cfg.set_pending_grid_config(GridConfigTarget::None);
        assert_eq!(cfg.set_grid_config(5).unwrap(), "");
    }

    /// SystemTailWindow/HeartbeatInterval mirror Go's i64-nanosecond
    /// duration math: wrap-around on overflow instead of panicking, and
    /// negative Go results (unrepresentable in std Duration) clamp to zero.
    #[test]
    fn test_duration_getters_go_overflow_semantics() {
        let dir = tempfile::tempdir().unwrap();
        let path = temp_config_path(&dir);

        // A valid config file (normalizeConfig only checks > 0) whose
        // minutes value overflows the naive `minutes * 60` u64 math:
        // Go: time.Duration(307445734561825861) * time.Minute wraps to
        // 44_000_000_000ns = 44s.
        fs::write(
            &path,
            r#"{"system_tail_window_minutes": 307445734561825861}"#,
        )
        .unwrap();
        let cfg = ConfigManager::new(&path);
        assert_eq!(
            cfg.snapshot().system_tail_window_minutes,
            307445734561825861
        );
        assert_eq!(cfg.system_tail_window(), Duration::from_secs(44));

        // Go: time.Duration(400000000000000000) * time.Minute wraps to
        // -320875195281702912ns; std Duration clamps that to zero.
        let mut cfg = cfg;
        cfg.config.system_tail_window_minutes = 400_000_000_000_000_000;
        assert_eq!(cfg.system_tail_window(), Duration::ZERO);

        // A type error on a later field makes loadOrCreateConfig return
        // before normalizeConfig (config.go:242-248), so a negative value
        // survives. Go returns -5m/-5s; std Duration clamps to zero.
        fs::write(
            &path,
            r#"{
  "system_tail_window_minutes": -5,
  "heartbeat_interval_seconds": -5,
  "left_sidebar_visible": 3
}"#,
        )
        .unwrap();
        let cfg = ConfigManager::new(&path);
        assert_eq!(cfg.snapshot().system_tail_window_minutes, -5);
        assert_eq!(cfg.snapshot().heartbeat_interval, -5);
        assert_eq!(cfg.system_tail_window(), Duration::ZERO);
        assert_eq!(cfg.heartbeat_interval(), Duration::ZERO);

        // Normalized values take the ordinary path.
        let cfg = ConfigManager::new(temp_config_path(&dir).with_extension("fresh"));
        assert_eq!(
            cfg.system_tail_window(),
            Duration::from_secs(DEFAULT_SYSTEM_TAIL_WINDOW_MINS as u64 * 60)
        );
        assert_eq!(
            cfg.heartbeat_interval(),
            Duration::from_secs(DEFAULT_HEARTBEAT_INTERVAL as u64)
        );
    }

    /// save() writes the config file with Go's os.WriteFile mode 0o644
    /// (config.go:345), not std's default 0o666.
    #[cfg(unix)]
    #[test]
    fn test_save_writes_config_file_with_go_mode() {
        use std::os::unix::fs::PermissionsExt;

        let dir = tempfile::tempdir().unwrap();

        // Probe the process umask with a default-created (0o666 pre-umask)
        // file so the assertion is umask-independent; 0o644 has no execute
        // bits, so only the rw portion of the umask matters.
        let probe = dir.path().join("probe");
        fs::write(&probe, b"x").unwrap();
        let umask_rw = 0o666 & !(fs::metadata(&probe).unwrap().permissions().mode() & 0o777);

        let path = temp_config_path(&dir);
        let _cfg = ConfigManager::new(&path);
        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o644 & !umask_rw);
    }

    /// Directory creation uses Go's modes: os.MkdirAll(dir, 0o755)
    /// (config.go:234, config.go:1084) and os.MkdirTemp's 0o700
    /// (config.go:1043), not std's default 0o777.
    #[cfg(unix)]
    #[test]
    fn test_dir_creation_uses_go_modes() {
        use std::os::unix::fs::PermissionsExt;

        let dir = tempfile::tempdir().unwrap();

        // Probe the process umask with a default-created (0o777 pre-umask)
        // directory so the assertions are umask-independent.
        let probe = dir.path().join("probe-dir");
        fs::create_dir(&probe).unwrap();
        let umask = 0o777 & !(fs::metadata(&probe).unwrap().permissions().mode() & 0o777);

        // loadOrCreateConfig creates missing parents with 0o755.
        let nested = dir.path().join("a").join("b");
        let _cfg = ConfigManager::new(nested.join(LEET_CONFIG_NAME));
        for d in [dir.path().join("a"), nested] {
            let mode = fs::metadata(&d).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o755 & !umask);
        }

        // ensureWritableDir creates missing directories with 0o755.
        let checked = dir.path().join("c").join("d");
        ensure_writable_dir(checked.to_str().unwrap()).unwrap();
        let mode = fs::metadata(&checked).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o755 & !umask);

        // The last-resort temp config dir is private (0o700).
        let tmp = mkdir_temp_wandb_leet().unwrap();
        let mode = fs::metadata(&tmp).unwrap().permissions().mode() & 0o777;
        let _ = fs::remove_dir(&tmp);
        assert_eq!(mode, 0o700 & !umask);
    }
}
