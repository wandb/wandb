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
func (m *ConfigManager) loadOrCreateConfig() error {
	data, err := os.ReadFile(m.path)

	// No config file yet, create and save it.
	if os.IsNotExist(err) {
		if dir := filepath.Dir(m.path); dir != "" {
			_ = os.MkdirAll(dir, 0755)
		}
		return m.save()
	}
	if err != nil {
		return err
	}

	if err := json.Unmarshal(data, &m.config); err != nil {
		return err
	}

	m.normalizeConfig()

	return nil
}

// normalizeConfig ensures all config values are within valid ranges.
func (m *ConfigManager) normalizeConfig() {
	// Clamp grid dimensions
	m.config.MetricsGrid.Rows = clamp(m.config.MetricsGrid.Rows, MinGridSize, MaxGridSize)
	m.config.MetricsGrid.Cols = clamp(m.config.MetricsGrid.Cols, MinGridSize, MaxGridSize)
	m.config.SystemGrid.Rows = clamp(m.config.SystemGrid.Rows, MinGridSize, MaxGridSize)
	m.config.SystemGrid.Cols = clamp(m.config.SystemGrid.Cols, MinGridSize, MaxGridSize)

	if _, ok := colorSchemes[m.config.ColorScheme]; !ok {
		m.config.ColorScheme = DefaultColorScheme
	}

	if m.config.HeartbeatInterval <= 0 {
		m.config.HeartbeatInterval = DefaultHeartbeatInterval
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
func (m *ConfigManager) save() error {
	data, err := json.MarshalIndent(m.config, "", "  ")
	if err != nil {
		return err
	}

	targetPath := m.path
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
func (m *ConfigManager) MetricsGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.MetricsGrid.Rows, m.config.MetricsGrid.Cols
}

// SetMetricsRows sets the metrics grid rows.
func (m *ConfigManager) SetMetricsRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("invalid value, must be [%d, %d]", MinGridSize, MaxGridSize)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Rows = rows
	return m.save()
}

// SetMetricsCols sets the metrics grid columns.
func (m *ConfigManager) SetMetricsCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("invalid value, must be [%d, %d]", MinGridSize, MaxGridSize)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Cols = cols
	return m.save()
}

// SystemGrid returns the system grid configuration.
func (m *ConfigManager) SystemGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.SystemGrid.Rows, m.config.SystemGrid.Cols
}

// SetSystemRows sets the system grid rows.
func (m *ConfigManager) SetSystemRows(rows int) error {
	if rows < MinGridSize || rows > MaxGridSize {
		return fmt.Errorf("invalid value, must be [%d, %d]", MinGridSize, MaxGridSize)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Rows = rows
	return m.save()
}

// SetSystemCols sets the system grid columns.
func (m *ConfigManager) SetSystemCols(cols int) error {
	if cols < MinGridSize || cols > MaxGridSize {
		return fmt.Errorf("invalid value, must be [%d, %d]", MinGridSize, MaxGridSize)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Cols = cols
	return m.save()
}

// ColorScheme returns the current color scheme.
func (m *ConfigManager) ColorScheme() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.ColorScheme
}

// HeartbeatInterval returns the heartbeat interval as a Duration.
func (m *ConfigManager) HeartbeatInterval() time.Duration {
	m.mu.RLock()
	defer m.mu.RUnlock()

	return time.Duration(m.config.HeartbeatInterval) * time.Second
}

// SetHeartbeatInterval sets the heartbeat interval in seconds.
func (m *ConfigManager) SetHeartbeatInterval(seconds int) error {
	if seconds <= 0 {
		return fmt.Errorf("invalid value, must be a positive integer")
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.HeartbeatInterval = seconds
	return m.save()
}

// LeftSidebarVisible returns whether the left sidebar should be visible.
func (m *ConfigManager) LeftSidebarVisible() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.LeftSidebarVisible
}

// SetLeftSidebarVisible sets the left sidebar visibility.
func (m *ConfigManager) SetLeftSidebarVisible(visible bool) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.LeftSidebarVisible = visible
	return m.save()
}

// RightSidebarVisible returns whether the right sidebar should be visible.
func (m *ConfigManager) RightSidebarVisible() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.RightSidebarVisible
}

// SetRightSidebarVisible sets the right sidebar visibility.
func (m *ConfigManager) SetRightSidebarVisible(visible bool) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.RightSidebarVisible = visible
	return m.save()
}
