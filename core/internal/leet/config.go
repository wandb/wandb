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
	DefaultSingleRunColorMode = ColorModePerSeries

	DefaultSystemColorScheme = "wandb-vibe-10"
	DefaultSystemColorMode   = ColorModePerSeries

	DefaultHeartbeatInterval = 15 // seconds
)

// Config stores the application configuration.
type Config struct {
	// MetricsGrid is the dimensions for the main metrics chart grid.
	MetricsGrid GridConfig `json:"metrics_grid"`

	// SystemGrid is the dimensions for the system metrics chart grid.
	SystemGrid GridConfig `json:"system_grid"`

	// ColorScheme is the color scheme to display the main metrics.
	ColorScheme string `json:"color_scheme"`

	// PerPlotColorScheme is the color scheme to use for main metrics
	// in single-run view when SingleRunColorMode is per_plot.
	// Gradient palettes work well here.
	PerPlotColorScheme string `json:"per_plot_color_scheme"`

	// SystemColorScheme is the color scheme for system metrics charts.
	SystemColorScheme string `json:"system_color_scheme"`

	// SystemColorMode determines color assignment strategy.
	// "per_plot": each chart gets next color from palette
	// "per_series": all single-series charts use base color, multi-series differentiate
	SystemColorMode string `json:"system_color_mode"`

	// SingleRunColorMode controls how charts are colored in single-run view:
	//  - per_series: stably-mapped run-id color for all charts
	//  - per_plot: each chart gets the next color from the palette (nice with gradients)
	SingleRunColorMode string `json:"single_run_color_mode"`

	// Heartbeat interval in seconds for live runs.
	//
	// Heartbeats are used to trigger .wandb file read attempts if no file watcher
	// events have been seen for a long time for a live file.
	HeartbeatInterval int `json:"heartbeat_interval_seconds"`

	// Sidebar visibility states.
	LeftSidebarVisible  bool `json:"left_sidebar_visible"`
	RightSidebarVisible bool `json:"right_sidebar_visible"`
}

// GridConfig represents grid dimensions.
type GridConfig struct {
	Rows int `json:"rows"`
	Cols int `json:"cols"`
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
			ColorScheme:         DefaultColorScheme,
			PerPlotColorScheme:  DefaultPerPlotColorScheme,
			SingleRunColorMode:  DefaultSingleRunColorMode,
			SystemColorScheme:   DefaultSystemColorScheme,
			SystemColorMode:     DefaultSystemColorMode,
			HeartbeatInterval:   DefaultHeartbeatInterval,
			LeftSidebarVisible:  true,
			RightSidebarVisible: true,
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

	if _, ok := colorSchemes[cm.config.ColorScheme]; !ok {
		cm.config.ColorScheme = DefaultColorScheme
	}

	if _, ok := colorSchemes[cm.config.PerPlotColorScheme]; !ok {
		cm.config.PerPlotColorScheme = DefaultPerPlotColorScheme
	}

	if _, ok := colorSchemes[cm.config.SystemColorScheme]; !ok {
		cm.config.SystemColorScheme = DefaultSystemColorScheme
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

// SystemColorMode returns the color assignment mode for system metrics.
func (cm *ConfigManager) SystemColorMode() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.SystemColorMode
}

// SetSystemColorScheme sets the system color scheme.
func (cm *ConfigManager) SetSystemColorScheme(scheme string) error {
	if _, ok := colorSchemes[scheme]; !ok {
		return fmt.Errorf("unknown color scheme: %s", scheme)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config.SystemColorScheme = scheme
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

	var err error

	switch pgc {
	case gridConfigMetricsCols:
		if err = cm.SetMetricsCols(num); err == nil { // success
			return fmt.Sprintf("Metrics grid columns set to %d", num), nil
		}
	case gridConfigMetricsRows:
		if err = cm.SetMetricsRows(num); err == nil { // success
			return fmt.Sprintf("Metrics grid rows set to %d", num), nil
		}
	case gridConfigSystemCols:
		if err = cm.SetSystemCols(num); err == nil { // success
			return fmt.Sprintf("System grid columns set to %d", num), nil
		}
	case gridConfigSystemRows:
		if err = cm.SetSystemRows(num); err == nil { // success
			return fmt.Sprintf("System grid rows set to %d", num), nil
		}
	}

	return "", err
}

// SetConfig replaces the full config (validated) and persists it.
func (cm *ConfigManager) SetConfig(cfg Config) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.config = cfg
	cm.normalizeConfig()
	return cm.save()
}

// GridConfigStatus returns the status message to display when awaiting grid config input.
func (cm *ConfigManager) GridConfigStatus() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	switch cm.pendingGridConfig {
	case gridConfigMetricsCols:
		return "Press 1-9 to set metrics grid columns (ESC to cancel)"
	case gridConfigMetricsRows:
		return "Press 1-9 to set metrics grid rows (ESC to cancel)"
	case gridConfigSystemCols:
		return "Press 1-9 to set system grid columns (ESC to cancel)"
	case gridConfigSystemRows:
		return "Press 1-9 to set system grid rows (ESC to cancel)"
	default:
		return ""
	}
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
