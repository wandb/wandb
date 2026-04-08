package leet

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
)

type gridConfigTarget int

const (
	gridConfigNone gridConfigTarget = iota
	gridConfigMetricsRows
	gridConfigMetricsCols
	gridConfigSystemRows
	gridConfigSystemCols
	gridConfigMediaRows
	gridConfigMediaCols
	gridConfigWorkspaceMetricsRows
	gridConfigWorkspaceMetricsCols
	gridConfigWorkspaceSystemRows
	gridConfigWorkspaceSystemCols
	gridConfigWorkspaceMediaRows
	gridConfigWorkspaceMediaCols
	gridConfigSymonRows
	gridConfigSymonCols
)

const (
	envConfigDir   = "WANDB_CONFIG_DIR"
	leetConfigName = "wandb-leet.json"

	// Chart grid size constraints.
	MinGridSize, MaxGridSize = 1, 9

	ColorModePerPlot   = "per_plot"   // Each chart gets next color
	ColorModePerSeries = "per_series" // All charts use base color, multi-series differentiate

	DefaultColorScheme        = "wandb-vibe-10"
	DefaultPerPlotColorScheme = "sunset-glow"
	DefaultTagColorScheme     = DefaultColorScheme
	DefaultSingleRunColorMode = ColorModePerSeries

	DefaultSystemColorScheme      = "wandb-vibe-10"
	DefaultFrenchFriesColorScheme = "viridis"
	DefaultSystemColorMode        = ColorModePerSeries
	DefaultSystemTailWindowMins   = 10

	DefaultHeartbeatInterval = 15 // seconds

	DefaultMediaGridRows          = 1
	DefaultMediaGridCols          = 2
	DefaultWorkspaceMediaGridRows = 1
	DefaultWorkspaceMediaGridCols = 2

	// Startup modes control what LEET does when launched without a specified run path
	// (i.e. `wandb beta leet` with no PATH).
	StartupModeWorkspaceLatest = "workspace_latest"  // Load workspace view and select latest run
	StartupModeSingleRunLatest = "single_run_latest" // Load latest run in the single-run view
	DefaultStartupMode         = StartupModeWorkspaceLatest
)

// Config stores the application configuration.
type Config struct {
	// StartupMode controls what happens when LEET is launched without --run-file.
	//  - workspace_latest: open workspace and auto-select the latest run
	//  - single_run_latest: open the latest run directly in single-run view
	StartupMode string `json:"startup_mode" leet:"label=Startup mode,desc=Initial view when launched without a run path.,options=startupModes"`

	// MetricsGrid is the dimensions for the metrics chart grid in single-run mode.
	MetricsGrid GridConfig `json:"metrics_grid" leet:"desc=main metrics grid"`

	// SystemGrid is the dimensions for the system metrics chart grid in single-run mode.
	SystemGrid GridConfig `json:"system_grid" leet:"desc=system metrics grid"`

	// MediaGrid is the dimensions for the media thumbnail grid in single-run mode.
	MediaGrid GridConfig `json:"media_grid" leet:"desc=single-run media grid"`

	// Grid dimensions in Workspace view.
	WorkspaceMetricsGrid GridConfig `json:"workspace_metrics_grid" leet:"desc=workspace metrics grid"`
	WorkspaceSystemGrid  GridConfig `json:"workspace_system_grid"  leet:"desc=workspace system metrics grid"`
	WorkspaceMediaGrid   GridConfig `json:"workspace_media_grid"   leet:"desc=workspace media grid"`

	// SymonGrid is the dimensions for the standalone system monitor chart grid.
	SymonGrid GridConfig `json:"symon_grid" leet:"desc=standalone system metrics grid"`

	// ColorScheme is the color scheme to display the main metrics.
	ColorScheme string `json:"color_scheme" leet:"desc=Palette for main run metrics charts (and run list colors).,options=colorSchemes"`

	// TagColorScheme is the color scheme for run tag badges in the overview sidebar.
	TagColorScheme string `json:"tag_color_scheme" leet:"label=Tag color scheme,desc=Palette for run tags in the overview sidebar.,options=colorSchemes"`

	// PerPlotColorScheme is the color scheme to use for main metrics
	// in single-run view when SingleRunColorMode is per_plot.
	// Gradient palettes work well here.
	PerPlotColorScheme string `json:"per_plot_color_scheme" leet:"label=Per-plot color scheme,desc=Palette for single-run view in per-plot mode. Gradients look nice here.,options=colorSchemes"`

	// SystemColorScheme is the color scheme for system metrics charts.
	SystemColorScheme string `json:"system_color_scheme" leet:"desc=Palette for system charts.,options=colorSchemes"`

	// FrenchFriesColorScheme is the color scheme for French Fries heatmaps.
	FrenchFriesColorScheme string `json:"french_fries_color_scheme" leet:"label=Bucketed heatmap color scheme,desc=Palette for percentage heatmaps (French Fries plots). Sequential palettes work best.,options=colorSchemes"`

	// SystemColorMode determines color assignment strategy.
	// "per_plot": each chart gets next color from palette
	// "per_series": all single-series charts use base color, multi-series differentiate
	SystemColorMode string `json:"system_color_mode" leet:"desc=Color system charts per plot or per series.,options=colorModes"`

	// SystemTailWindowMinutes controls the default live tail window for system charts.
	// Users can still zoom out to show the full history.
	SystemTailWindowMinutes int `json:"system_tail_window_minutes" leet:"label=System tail window (min),desc=Default live tail window for system charts. Zooming out can show full history.,min=1"`

	// SingleRunColorMode controls how charts are colored in single-run view:
	//  - per_series: stably-mapped run-id color for all charts
	//  - per_plot: each chart gets the next color from the palette (nice with gradients)
	SingleRunColorMode string `json:"single_run_color_mode" leet:"label=Single-run color mode,desc=Color single-run charts per plot or use stable run-id color for all charts.,options=colorModes"`

	// Heartbeat interval in seconds for live runs.
	//
	// Heartbeats are used to trigger .wandb file read attempts if no file watcher
	// events have been seen for a long time for a live file.
	HeartbeatInterval int `json:"heartbeat_interval_seconds" leet:"label=Heartbeat interval (sec),desc=Polling heartbeat for live runs.,min=1"`

	// Single-run view sidebar visibility states.
	LeftSidebarVisible  bool `json:"left_sidebar_visible"  leet:"desc=Show left sidebar in single run view by default."`
	RightSidebarVisible bool `json:"right_sidebar_visible" leet:"desc=Show right sidebar in single run view by default."`
	MetricsGridVisible  bool `json:"metrics_grid_visible"  leet:"desc=Show metrics grid in single run mode by default."`
	ConsoleLogsVisible  bool `json:"console_logs_visible"  leet:"desc=Show console logs pane in single run mode by default."`
	MediaVisible        bool `json:"media_visible"         leet:"desc=Show media pane in single run mode by default."`

	// Workspace view pane visibility states.
	WorkspaceOverviewVisible      bool `json:"workspace_overview_visible"       leet:"desc=Show run overview sidebar in workspace mode by default."`
	WorkspaceMetricsGridVisible   bool `json:"workspace_metrics_grid_visible"   leet:"desc=Show metrics grid in workspace mode by default."`
	WorkspaceSystemMetricsVisible bool `json:"workspace_system_metrics_visible" leet:"desc=Show system metrics pane in workspace mode by default."`
	WorkspaceConsoleLogsVisible   bool `json:"workspace_console_logs_visible"   leet:"desc=Show console logs pane in workspace mode by default."`
	WorkspaceMediaVisible         bool `json:"workspace_media_visible"          leet:"desc=Show media pane in workspace mode by default."`
}

// GridConfig represents grid dimensions.
type GridConfig struct {
	Rows int `json:"rows" leet:"min=1,max=9"`
	Cols int `json:"cols" leet:"min=1,max=9"`
}

// ConfigManager manages application configuration with thread-safe access
// and automatic persistence to disk.
//
// All setter methods automatically save changes to disk.
// Getters use read locks for concurrent access.
type ConfigManager struct {
	mu                sync.RWMutex
	path              string
	config            Config
	pendingGridConfig gridConfigTarget
	logger            *observability.CoreLogger
}

func NewConfigManager(path string, logger *observability.CoreLogger) *ConfigManager {
	cm := &ConfigManager{
		path: path,
		config: Config{
			MetricsGrid: GridConfig{
				Rows: DefaultMetricsGridRows,
				Cols: DefaultMetricsGridCols,
			},
			SystemGrid: GridConfig{
				Rows: DefaultSystemGridRows,
				Cols: DefaultSystemGridCols,
			},
			MediaGrid: GridConfig{
				Rows: DefaultMediaGridRows,
				Cols: DefaultMediaGridCols,
			},
			WorkspaceMetricsGrid: GridConfig{
				Rows: DefaultWorkspaceMetricsGridRows,
				Cols: DefaultWorkspaceMetricsGridCols,
			},
			WorkspaceSystemGrid: GridConfig{
				Rows: DefaultWorkspaceSystemGridRows,
				Cols: DefaultWorkspaceSystemGridCols,
			},
			WorkspaceMediaGrid: GridConfig{
				Rows: DefaultWorkspaceMediaGridRows,
				Cols: DefaultWorkspaceMediaGridCols,
			},
			SymonGrid: GridConfig{
				Rows: DefaultSymonGridRows,
				Cols: DefaultSymonGridCols,
			},
			StartupMode:                   DefaultStartupMode,
			ColorScheme:                   DefaultColorScheme,
			PerPlotColorScheme:            DefaultPerPlotColorScheme,
			TagColorScheme:                DefaultTagColorScheme,
			SingleRunColorMode:            DefaultSingleRunColorMode,
			SystemColorScheme:             DefaultSystemColorScheme,
			FrenchFriesColorScheme:        DefaultFrenchFriesColorScheme,
			SystemColorMode:               DefaultSystemColorMode,
			SystemTailWindowMinutes:       DefaultSystemTailWindowMins,
			HeartbeatInterval:             DefaultHeartbeatInterval,
			LeftSidebarVisible:            true,
			RightSidebarVisible:           true,
			MetricsGridVisible:            true,
			ConsoleLogsVisible:            false,
			MediaVisible:                  false,
			WorkspaceOverviewVisible:      true,
			WorkspaceMetricsGridVisible:   true,
			WorkspaceSystemMetricsVisible: false,
			WorkspaceConsoleLogsVisible:   false,
			WorkspaceMediaVisible:         false,
		},
		logger: logger,
	}
	if err := cm.loadOrCreateConfig(); err != nil {
		cm.logger.Error(fmt.Sprintf("config: error loading or creating:%v", err))
	}

	return cm
}

// loadOrCreateConfig loads the configuration from disk or stores and uses defaults.
func (cm *ConfigManager) loadOrCreateConfig() error {
	data, err := os.ReadFile(cm.path)

	// No config file yet, create and save it.
	if os.IsNotExist(err) {
		if dir := filepath.Dir(cm.path); dir != "" {
			_ = os.MkdirAll(dir, 0o755)
		}
		return cm.save()
	}
	if err != nil {
		return err
	}

	if err := json.Unmarshal(data, &cm.config); err != nil {
		return err
	}

	cm.normalizeConfig()

	return nil
}

// normalizeConfig ensures all config values are within valid ranges.
func (cm *ConfigManager) normalizeConfig() {
	// Clamp grid dimensions
	cm.config.MetricsGrid.Rows = clamp(cm.config.MetricsGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.MetricsGrid.Cols = clamp(cm.config.MetricsGrid.Cols, MinGridSize, MaxGridSize)
	cm.config.SystemGrid.Rows = clamp(cm.config.SystemGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.SystemGrid.Cols = clamp(cm.config.SystemGrid.Cols, MinGridSize, MaxGridSize)
	cm.config.MediaGrid.Rows = clamp(cm.config.MediaGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.MediaGrid.Cols = clamp(cm.config.MediaGrid.Cols, MinGridSize, MaxGridSize)

	cm.config.WorkspaceMetricsGrid.Cols = clamp(
		cm.config.WorkspaceMetricsGrid.Cols, MinGridSize, MaxGridSize)
	cm.config.WorkspaceMetricsGrid.Rows = clamp(
		cm.config.WorkspaceMetricsGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.WorkspaceSystemGrid.Rows = clamp(
		cm.config.WorkspaceSystemGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.WorkspaceSystemGrid.Cols = clamp(
		cm.config.WorkspaceSystemGrid.Cols, MinGridSize, MaxGridSize)
	cm.config.WorkspaceMediaGrid.Rows = clamp(
		cm.config.WorkspaceMediaGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.WorkspaceMediaGrid.Cols = clamp(
		cm.config.WorkspaceMediaGrid.Cols, MinGridSize, MaxGridSize)
	cm.config.SymonGrid.Rows = clamp(
		cm.config.SymonGrid.Rows, MinGridSize, MaxGridSize)
	cm.config.SymonGrid.Cols = clamp(
		cm.config.SymonGrid.Cols, MinGridSize, MaxGridSize)

	if _, ok := colorSchemes[cm.config.ColorScheme]; !ok {
		cm.config.ColorScheme = DefaultColorScheme
	}

	if _, ok := colorSchemes[cm.config.PerPlotColorScheme]; !ok {
		cm.config.PerPlotColorScheme = DefaultPerPlotColorScheme
	}

	if _, ok := colorSchemes[cm.config.SystemColorScheme]; !ok {
		cm.config.SystemColorScheme = DefaultSystemColorScheme
	}

	if _, ok := colorSchemes[cm.config.FrenchFriesColorScheme]; !ok {
		cm.config.FrenchFriesColorScheme = DefaultFrenchFriesColorScheme
	}

	if _, ok := colorSchemes[cm.config.TagColorScheme]; !ok {
		cm.config.TagColorScheme = DefaultTagColorScheme
	}

	if cm.config.SystemColorMode != ColorModePerPlot &&
		cm.config.SystemColorMode != ColorModePerSeries {
		cm.config.SystemColorMode = DefaultSystemColorMode
	}

	if cm.config.SingleRunColorMode != ColorModePerPlot &&
		cm.config.SingleRunColorMode != ColorModePerSeries {
		cm.config.SingleRunColorMode = DefaultSingleRunColorMode
	}

	if cm.config.HeartbeatInterval <= 0 {
		cm.config.HeartbeatInterval = DefaultHeartbeatInterval
	}

	if cm.config.SystemTailWindowMinutes <= 0 {
		cm.config.SystemTailWindowMinutes = DefaultSystemTailWindowMins
	}

	if cm.config.StartupMode != StartupModeWorkspaceLatest &&
		cm.config.StartupMode != StartupModeSingleRunLatest {
		cm.config.StartupMode = DefaultStartupMode
	}
}

func clamp(val, minimum, maximum int) int {
	if val < minimum {
		return minimum
	}
	if val > maximum {
		return maximum
	}
	return val
}

// save writes the current configuration to disk.
//
// Must be called while holding the lock.
func (cm *ConfigManager) save() error {
	data, err := json.MarshalIndent(cm.config, "", "  ")
	if err != nil {
		return err
	}

	targetPath := cm.path
	tempPath := targetPath + ".tmp"

	// Write atomically via temp file + rename.
	if err := os.WriteFile(tempPath, data, 0o644); err != nil {
		return fmt.Errorf("failed to write temp config file: %v", err)
	}
	if err := os.Rename(tempPath, targetPath); err != nil {
		return fmt.Errorf("failed to rename tmp config file: %v", err)
	}

	return nil
}

// MetricsGrid returns the metrics grid configuration.
func (cm *ConfigManager) MetricsGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.MetricsGrid.Rows, cm.config.MetricsGrid.Cols
}

// SetMetricsRows sets the metrics grid rows.
func (cm *ConfigManager) SetMetricsRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MetricsGrid.Rows = rows
	return cm.save()
}

// SetMetricsCols sets the metrics grid columns.
func (cm *ConfigManager) SetMetricsCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MetricsGrid.Cols = cols
	return cm.save()
}

// SystemGrid returns the system grid configuration.
func (cm *ConfigManager) SystemGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SystemGrid.Rows, cm.config.SystemGrid.Cols
}

// SetSystemRows sets the system grid rows.
func (cm *ConfigManager) SetSystemRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemGrid.Rows = rows
	return cm.save()
}

// SetSystemCols sets the system grid columns.
func (cm *ConfigManager) SetSystemCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemGrid.Cols = cols
	return cm.save()
}

// MediaGrid returns the media grid configuration.
func (cm *ConfigManager) MediaGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.MediaGrid.Rows, cm.config.MediaGrid.Cols
}

// SetMediaRows sets the media grid rows.
func (cm *ConfigManager) SetMediaRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MediaGrid.Rows = rows
	return cm.save()
}

// SetMediaCols sets the media grid columns.
func (cm *ConfigManager) SetMediaCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MediaGrid.Cols = cols
	return cm.save()
}

// WorkspaceMetricsGrid returns the workspace metrics grid configuration.
func (cm *ConfigManager) WorkspaceMetricsGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceMetricsGrid.Rows, cm.config.WorkspaceMetricsGrid.Cols
}

func (cm *ConfigManager) SetWorkspaceMetricsRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMetricsGrid.Rows = rows
	return cm.save()
}

func (cm *ConfigManager) SetWorkspaceMetricsCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMetricsGrid.Cols = cols
	return cm.save()
}

// WorkspaceSystemGrid returns the workspace system grid configuration.
func (cm *ConfigManager) WorkspaceSystemGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceSystemGrid.Rows, cm.config.WorkspaceSystemGrid.Cols
}

// WorkspaceMediaGrid returns the workspace media grid configuration.
func (cm *ConfigManager) WorkspaceMediaGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceMediaGrid.Rows, cm.config.WorkspaceMediaGrid.Cols
}

// SymonGrid returns the standalone system monitor grid configuration.
func (cm *ConfigManager) SymonGrid() (rows, cols int) {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SymonGrid.Rows, cm.config.SymonGrid.Cols
}

func (cm *ConfigManager) SetWorkspaceSystemRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceSystemGrid.Rows = rows
	return cm.save()
}

func (cm *ConfigManager) SetWorkspaceSystemCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceSystemGrid.Cols = cols
	return cm.save()
}

func (cm *ConfigManager) SetWorkspaceMediaRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMediaGrid.Rows = rows
	return cm.save()
}

func (cm *ConfigManager) SetWorkspaceMediaCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMediaGrid.Cols = cols
	return cm.save()
}

func (cm *ConfigManager) SetSymonRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("rows must be between %d and %d, got %d", MinGridSize, MaxGridSize, rows)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SymonGrid.Rows = rows
	return cm.save()
}

func (cm *ConfigManager) SetSymonCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("cols must be between %d and %d, got %d", MinGridSize, MaxGridSize, cols)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SymonGrid.Cols = cols
	return cm.save()
}

// Path returns the on-disk config path.
func (cm *ConfigManager) Path() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.path
}

// Snapshot returns a copy of the current config.
func (cm *ConfigManager) Snapshot() Config {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config
}

// StartupMode returns the configured startup mode.
func (cm *ConfigManager) StartupMode() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.StartupMode
}

// SetStartupMode sets the startup mode and persists it.
func (cm *ConfigManager) SetStartupMode(mode string) error {
	if mode != StartupModeWorkspaceLatest && mode != StartupModeSingleRunLatest {
		return fmt.Errorf(
			"startup_mode must be %q or %q, got %q",
			StartupModeWorkspaceLatest, StartupModeSingleRunLatest, mode,
		)
	}
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.StartupMode = mode
	return cm.save()
}

// ColorScheme returns the current color scheme.
func (cm *ConfigManager) ColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.ColorScheme
}

func (cm *ConfigManager) SetColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %q", scheme)
	}
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.ColorScheme = scheme
	return cm.save()
}

func (cm *ConfigManager) PerPlotColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.PerPlotColorScheme
}

func (cm *ConfigManager) SetPerPlotColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %q", scheme)
	}
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.PerPlotColorScheme = scheme
	return cm.save()
}

func (cm *ConfigManager) TagColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.TagColorScheme
}

func (cm *ConfigManager) SetTagColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %q", scheme)
	}
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.TagColorScheme = scheme
	return cm.save()
}

func (cm *ConfigManager) SingleRunColorMode() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SingleRunColorMode
}

func (cm *ConfigManager) SetSingleRunColorMode(mode string) error {
	if mode != ColorModePerPlot && mode != ColorModePerSeries {
		return fmt.Errorf(
			"single_run_color_mode must be %q or %q, got %q",
			ColorModePerPlot, ColorModePerSeries, mode,
		)
	}
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SingleRunColorMode = mode
	return cm.save()
}

// SystemColorScheme returns the color scheme for system metrics.
func (cm *ConfigManager) SystemColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SystemColorScheme
}

// FrenchFriesColorScheme returns the color scheme for French Fries heatmaps.
func (cm *ConfigManager) FrenchFriesColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.FrenchFriesColorScheme
}

// SystemColorMode returns the color assignment mode for system metrics.
func (cm *ConfigManager) SystemColorMode() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SystemColorMode
}

// SetSystemColorScheme sets the system color scheme.
func (cm *ConfigManager) SetSystemColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %q", scheme)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemColorScheme = scheme
	return cm.save()
}

// SetFrenchFriesColorScheme sets the French Fries heatmap color scheme.
func (cm *ConfigManager) SetFrenchFriesColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %q", scheme)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.FrenchFriesColorScheme = scheme
	return cm.save()
}

// SetSystemColorMode sets the system color mode.
func (cm *ConfigManager) SetSystemColorMode(mode string) error {
	if mode != ColorModePerPlot && mode != ColorModePerSeries {
		return fmt.Errorf("invalid color mode: %s (must be %s or %s)",
			mode, ColorModePerPlot, ColorModePerSeries)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemColorMode = mode
	return cm.save()
}

// SystemTailWindow returns the default live tail window for system charts.
func (cm *ConfigManager) SystemTailWindow() time.Duration {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	return time.Duration(cm.config.SystemTailWindowMinutes) * time.Minute
}

// SetSystemTailWindowMinutes sets the default live tail window for system charts.
func (cm *ConfigManager) SetSystemTailWindowMinutes(minutes int) error {
	if minutes <= 0 {
		return fmt.Errorf("system tail window must be a positive integer")
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemTailWindowMinutes = minutes
	return cm.save()
}

// HeartbeatInterval returns the heartbeat interval as a Duration.
func (cm *ConfigManager) HeartbeatInterval() time.Duration {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	return time.Duration(cm.config.HeartbeatInterval) * time.Second
}

// SetHeartbeatInterval sets the heartbeat interval in seconds.
func (cm *ConfigManager) SetHeartbeatInterval(seconds int) error {
	if seconds <= 0 {
		return fmt.Errorf("heartbeat interval must be a positive integer")
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.HeartbeatInterval = seconds
	return cm.save()
}

// LeftSidebarVisible returns whether the left sidebar should be visible.
func (cm *ConfigManager) LeftSidebarVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.LeftSidebarVisible
}

// SetLeftSidebarVisible sets the left sidebar visibility.
func (cm *ConfigManager) SetLeftSidebarVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.LeftSidebarVisible = visible
	return cm.save()
}

// RightSidebarVisible returns whether the right sidebar should be visible.
func (cm *ConfigManager) RightSidebarVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.RightSidebarVisible
}

// SetRightSidebarVisible sets the right sidebar visibility.
func (cm *ConfigManager) SetRightSidebarVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.RightSidebarVisible = visible
	return cm.save()
}

// ConsoleLogsVisible returns whether the console logs pane
// should be visible in single-run mode.
func (cm *ConfigManager) ConsoleLogsVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.ConsoleLogsVisible
}

// SetConsoleLogsVisible sets the single-run console logs pane visibility.
func (cm *ConfigManager) SetConsoleLogsVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.ConsoleLogsVisible = visible
	return cm.save()
}

// MetricsGridVisible returns whether the metrics grid should be visible in single-run mode.
func (cm *ConfigManager) MetricsGridVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.MetricsGridVisible
}

// SetMetricsGridVisible sets the single-run metrics grid visibility.
func (cm *ConfigManager) SetMetricsGridVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MetricsGridVisible = visible
	return cm.save()
}

// MediaVisible returns whether the media pane should be visible in single-run mode.
func (cm *ConfigManager) MediaVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.MediaVisible
}

// SetMediaVisible sets the single-run media pane visibility.
func (cm *ConfigManager) SetMediaVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.MediaVisible = visible
	return cm.save()
}

func (cm *ConfigManager) IsAwaitingGridConfig() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.pendingGridConfig != gridConfigNone
}

// SetPendingGridConfig set the pending metrics/system grid configuration target.
func (cm *ConfigManager) SetPendingGridConfig(gct gridConfigTarget) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.pendingGridConfig = gct
}

// SetGridConfig sets a value for a pending grid config target (metrics or system).
func (cm *ConfigManager) SetGridConfig(num int) (string, error) {
	cm.mu.RLock()
	pgc := cm.pendingGridConfig
	cm.mu.RUnlock()

	type entry struct {
		setter func(int) error
		label  string
	}
	table := map[gridConfigTarget]entry{
		gridConfigMetricsCols: {cm.SetMetricsCols,
			"Metrics grid columns"},
		gridConfigMetricsRows: {cm.SetMetricsRows,
			"Metrics grid rows"},
		gridConfigSystemCols: {cm.SetSystemCols,
			"System grid columns"},
		gridConfigSystemRows: {cm.SetSystemRows,
			"System grid rows"},
		gridConfigMediaCols: {cm.SetMediaCols,
			"Media grid columns"},
		gridConfigMediaRows: {cm.SetMediaRows,
			"Media grid rows"},
		gridConfigWorkspaceMetricsCols: {cm.SetWorkspaceMetricsCols,
			"Workspace metrics grid columns"},
		gridConfigWorkspaceMetricsRows: {cm.SetWorkspaceMetricsRows,
			"Workspace metrics grid rows"},
		gridConfigWorkspaceSystemCols: {cm.SetWorkspaceSystemCols,
			"Workspace system grid columns"},
		gridConfigWorkspaceSystemRows: {cm.SetWorkspaceSystemRows,
			"Workspace system grid rows"},
		gridConfigWorkspaceMediaCols: {cm.SetWorkspaceMediaCols,
			"Workspace media grid columns"},
		gridConfigWorkspaceMediaRows: {cm.SetWorkspaceMediaRows,
			"Workspace media grid rows"},
		gridConfigSymonCols: {cm.SetSymonCols,
			"Symon grid columns"},
		gridConfigSymonRows: {cm.SetSymonRows,
			"Symon grid rows"},
	}

	e, ok := table[pgc]
	if !ok {
		return "", nil
	}
	if err := e.setter(num); err != nil {
		return "", err
	}
	return fmt.Sprintf("%s set to %d", e.label, num), nil
}

// SetConfig replaces the full config (validated) and persists it.
func (cm *ConfigManager) SetConfig(cfg *Config) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config = *cfg
	cm.normalizeConfig()
	return cm.save()
}

// GridConfigStatus returns the status message to display when awaiting grid config input.
func (cm *ConfigManager) GridConfigStatus() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	switch cm.pendingGridConfig {
	case gridConfigMetricsCols, gridConfigWorkspaceMetricsCols:
		return "Press 1-9 to set metrics grid columns (ESC to cancel)"
	case gridConfigMetricsRows, gridConfigWorkspaceMetricsRows:
		return "Press 1-9 to set metrics grid rows (ESC to cancel)"
	case gridConfigSystemCols, gridConfigWorkspaceSystemCols, gridConfigSymonCols:
		return "Press 1-9 to set system grid columns (ESC to cancel)"
	case gridConfigSystemRows, gridConfigWorkspaceSystemRows, gridConfigSymonRows:
		return "Press 1-9 to set system grid rows (ESC to cancel)"
	case gridConfigMediaCols, gridConfigWorkspaceMediaCols:
		return "Press 1-9 to set media grid columns (ESC to cancel)"
	case gridConfigMediaRows, gridConfigWorkspaceMediaRows:
		return "Press 1-9 to set media grid rows (ESC to cancel)"

	default:
		return ""
	}
}

// WorkspaceOverviewVisible returns whether the overview sidebar should be
// visible in workspace mode.
func (cm *ConfigManager) WorkspaceOverviewVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceOverviewVisible
}

// SetWorkspaceOverviewVisible sets the workspace overview sidebar visibility.
func (cm *ConfigManager) SetWorkspaceOverviewVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceOverviewVisible = visible
	return cm.save()
}

// WorkspaceSystemMetricsVisible returns whether the system metrics pane
// should be visible in workspace mode.
func (cm *ConfigManager) WorkspaceSystemMetricsVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceSystemMetricsVisible
}

// SetWorkspaceSystemMetricsVisible sets the workspace system metrics pane visibility.
func (cm *ConfigManager) SetWorkspaceSystemMetricsVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceSystemMetricsVisible = visible
	return cm.save()
}

// WorkspaceConsoleLogsVisible returns whether the console logs pane
// should be visible in workspace mode.
func (cm *ConfigManager) WorkspaceConsoleLogsVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceConsoleLogsVisible
}

// SetWorkspaceConsoleLogsVisible sets the workspace console logs pane visibility.
func (cm *ConfigManager) SetWorkspaceConsoleLogsVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceConsoleLogsVisible = visible
	return cm.save()
}

// WorkspaceMetricsGridVisible returns whether the metrics grid should be visible in workspace mode.
func (cm *ConfigManager) WorkspaceMetricsGridVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceMetricsGridVisible
}

// SetWorkspaceMetricsGridVisible sets the workspace metrics grid visibility.
func (cm *ConfigManager) SetWorkspaceMetricsGridVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMetricsGridVisible = visible
	return cm.save()
}

// WorkspaceMediaVisible returns whether the media pane should be visible in workspace mode.
func (cm *ConfigManager) WorkspaceMediaVisible() bool {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.WorkspaceMediaVisible
}

// SetWorkspaceMediaVisible sets the workspace media pane visibility.
func (cm *ConfigManager) SetWorkspaceMediaVisible(visible bool) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.WorkspaceMediaVisible = visible
	return cm.save()
}

// leetConfigPath returns the path where the config should be stored.
//
// Matches the Python logic (same directory as the system "settings" file),
// with fallbacks to UserConfigDir and a temp dir.
func leetConfigPath() string {
	// 1) Honor WANDB_CONFIG_DIR (like in Python)
	if raw := strings.TrimSpace(os.Getenv(envConfigDir)); raw != "" {
		if p, ok := configPathFromDir(raw); ok {
			return p
		}
	}

	// 2) Default to ~/.config/wandb (like in Python)
	if home, err := os.UserHomeDir(); err == nil {
		if p, ok := configPathFromDir(filepath.Join(home, ".config", "wandb")); ok {
			return p
		}
	}

	// 3) Fallback: OS user config dir (/wandb)
	if base, err := os.UserConfigDir(); err == nil {
		if p, ok := configPathFromDir(filepath.Join(base, "wandb")); ok {
			return p
		}
	}

	// 4) Last resort: a fresh temp dir
	if tmp, err := os.MkdirTemp("", "wandb-leet-*"); err == nil {
		return filepath.Join(tmp, leetConfigName)
	}

	// Extremely unlikely final fallback
	return filepath.Join(os.TempDir(), leetConfigName)
}

func configPathFromDir(dir string) (string, bool) {
	d := expandAndClean(dir)
	if err := ensureWritableDir(d); err != nil {
		return "", false
	}
	return filepath.Join(d, leetConfigName), true
}

func expandAndClean(p string) string {
	p = strings.TrimSpace(p)
	if p == "" {
		return p
	}
	if strings.HasPrefix(p, "~") {
		if home, err := os.UserHomeDir(); err == nil {
			if len(p) == 1 {
				p = home
			} else if p[1] == '/' || p[1] == '\\' {
				p = filepath.Join(home, p[2:])
			}
		}
	}
	if abs, err := filepath.Abs(p); err == nil {
		p = abs
	}
	return filepath.Clean(p)
}

// ensureWritableDir verifies directory writability without leaving files behind.
func ensureWritableDir(dir string) error {
	if dir == "" {
		return errors.New("empty dir")
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".wandb-leet-writecheck-*")
	if err != nil {
		return err
	}
	name := f.Name()
	_ = f.Close()
	_ = os.Remove(name)
	return nil
}
