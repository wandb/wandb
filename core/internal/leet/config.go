package leet

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const DefaultHeartbeatInterval = 15 // seconds

// Config represents the application configuration.
type Config struct {
	// MetricsGrid is the dimentions for the main metrics chart grid.
	MetricsGrid GridConfig `json:"metrics_grid"`

	// SystemGrid is the dimentions for the system metrics chart grid.
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

// ConfigManager handles configuration loading and saving.
type ConfigManager struct {
	config     Config
	configPath string
	mu         sync.RWMutex
}

// Global config instance.
var (
	configManager *ConfigManager
	configOnce    sync.Once
)

// GetConfig returns the singleton config manager.
func GetConfig() *ConfigManager {
	configOnce.Do(func() {
		configDir, _ := os.UserConfigDir()
		leetConfigDir := filepath.Join(configDir, "wandb-leet")
		configPath := filepath.Join(leetConfigDir, "config.json")

		configManager = &ConfigManager{
			configPath: configPath,
			config: Config{
				MetricsGrid:       GridConfig{Rows: DefaultMetricsGridRows, Cols: DefaultMetricsGridCols},
				SystemGrid:        GridConfig{Rows: DefaultSystemGridRows, Cols: DefaultSystemGridCols},
				ColorScheme:       "sunset-glow",
				HeartbeatInterval: DefaultHeartbeatInterval,
			},
		}
	})
	return configManager
}

// Load loads the configuration from disk or uses defaults.
func (m *ConfigManager) Load() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	data, err := os.ReadFile(m.configPath)
	if err != nil {
		if os.IsNotExist(err) {
			// No config file yet, ensure directory exists
			if dir := filepath.Dir(m.configPath); dir != "" {
				_ = os.MkdirAll(dir, 0755)
			}
			return m.save()
		}
		return err
	}

	if err := json.Unmarshal(data, &m.config); err != nil {
		return err
	}

	// Ensure heartbeat interval has a reasonable value.
	if m.config.HeartbeatInterval <= 0 {
		m.config.HeartbeatInterval = DefaultHeartbeatInterval
	}

	return nil
}

// save writes the current configuration to disk.
//
// Must be called with lock held.
func (m *ConfigManager) save() error {
	data, err := json.MarshalIndent(m.config, "", "  ")
	if err != nil {
		return err
	}

	// Write atomically
	tempPath := m.configPath + ".tmp"
	if err := os.WriteFile(tempPath, data, 0644); err != nil {
		return err
	}
	return os.Rename(tempPath, m.configPath)
}

// GetMetricsGrid returns the metrics grid configuration.
func (m *ConfigManager) GetMetricsGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.MetricsGrid.Rows, m.config.MetricsGrid.Cols
}

// SetMetricsRows sets the metrics grid rows.
func (m *ConfigManager) SetMetricsRows(rows int) error {
	if rows < 1 || rows > 9 {
		return nil // silently ignore invalid values
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Rows = rows
	return m.save()
}

// SetMetricsCols sets the metrics grid columns.
func (m *ConfigManager) SetMetricsCols(cols int) error {
	if cols < 1 || cols > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Cols = cols
	return m.save()
}

// GetSystemGrid returns the system grid configuration.
func (m *ConfigManager) GetSystemGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.SystemGrid.Rows, m.config.SystemGrid.Cols
}

// SetSystemRows sets the system grid rows.
func (m *ConfigManager) SetSystemRows(rows int) error {
	if rows < 1 || rows > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Rows = rows
	return m.save()
}

// SetSystemCols sets the system grid columns.
func (m *ConfigManager) SetSystemCols(cols int) error {
	if cols < 1 || cols > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Cols = cols
	return m.save()
}

// GetColorScheme returns the current color scheme.
func (m *ConfigManager) GetColorScheme() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.ColorScheme
}

// GetHeartbeatInterval returns the heartbeat interval as a Duration.
func (m *ConfigManager) GetHeartbeatInterval() time.Duration {
	m.mu.RLock()
	defer m.mu.RUnlock()

	interval := m.config.HeartbeatInterval
	if interval <= 0 {
		interval = DefaultHeartbeatInterval
	}

	return time.Duration(interval) * time.Second
}

// SetHeartbeatInterval sets the heartbeat interval in seconds.
func (m *ConfigManager) SetHeartbeatInterval(seconds int) error {
	if seconds <= 0 {
		return nil // silently ignore invalid values
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.HeartbeatInterval = seconds
	return m.save()
}

// GetLeftSidebarVisible returns whether the left sidebar should be visible.
func (m *ConfigManager) GetLeftSidebarVisible() bool {
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

// GetRightSidebarVisible returns whether the right sidebar should be visible.
func (m *ConfigManager) GetRightSidebarVisible() bool {
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

// SetPathForTests overrides the on-disk path used to load/save the config.
//
// Call this in tests before Load or any Set* method.
// Production code should not call this.
func (m *ConfigManager) SetPathForTests(path string) {
	m.mu.Lock()
	m.configPath = path
	m.mu.Unlock()
}
