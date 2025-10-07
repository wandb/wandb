package leet

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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
	// Chart grid size constraints.
	MinGridSize = 1
	MaxGridSize = 9

	DefaultColorScheme       = "sunset-glow"
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
	mu     sync.RWMutex
	path   string
	config Config
	logger *observability.CoreLogger
}

func NewConfigManager(path string, logger *observability.CoreLogger) *ConfigManager {
	cm := &ConfigManager{
		path: path,
		config: Config{
			MetricsGrid:       GridConfig{Rows: DefaultMetricsGridRows, Cols: DefaultMetricsGridCols},
			SystemGrid:        GridConfig{Rows: DefaultSystemGridRows, Cols: DefaultSystemGridCols},
			ColorScheme:       DefaultColorScheme,
			HeartbeatInterval: DefaultHeartbeatInterval,
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
			_ = os.MkdirAll(dir, 0755)
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

	if cm.config.HeartbeatInterval <= 0 {
		cm.config.HeartbeatInterval = DefaultHeartbeatInterval
	}
}

func clamp(val, min, max int) int {
	if val < min {
		return min
	}
	if val > max {
		return max
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
	if err := os.WriteFile(tempPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write temp config file: %v", err)
	}
	if err := os.Rename(tempPath, targetPath); err != nil {
		return fmt.Errorf("failed to rename tmp config file: %v", err)
	}

	return nil
}

// MetricsGrid returns the metrics grid configuration.
func (cm *ConfigManager) MetricsGrid() (int, int) {
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
func (cm *ConfigManager) SystemGrid() (int, int) {
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

// ColorScheme returns the current color scheme.
func (cm *ConfigManager) ColorScheme() string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config.ColorScheme
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
