//go:build !wandb_core

package leet

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
)

// Config represents the application configuration
type Config struct {
	MetricsGrid GridConfig `json:"metrics_grid"`
	SystemGrid  GridConfig `json:"system_grid"`
	ColorScheme string     `json:"color_scheme"`
}

// GridConfig represents grid dimensions
type GridConfig struct {
	Rows int `json:"rows"`
	Cols int `json:"cols"`
}

// ConfigManager handles configuration loading and saving
type ConfigManager struct {
	config     Config
	configPath string
	mu         sync.RWMutex
}

// Global config instance
var (
	configManager *ConfigManager
	configOnce    sync.Once
)

// GetConfig returns the singleton config manager
func GetConfig() *ConfigManager {
	configOnce.Do(func() {
		configDir, _ := os.UserConfigDir()
		leetConfigDir := filepath.Join(configDir, "wandb-leet")
		configPath := filepath.Join(leetConfigDir, "config.json")

		configManager = &ConfigManager{
			configPath: configPath,
			config: Config{
				MetricsGrid: GridConfig{Rows: 3, Cols: 5},
				SystemGrid:  GridConfig{Rows: 3, Cols: 2},
				ColorScheme: "sunset-glow",
			},
		}
	})
	return configManager
}

// Load loads the configuration from disk or uses defaults
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

	return json.Unmarshal(data, &m.config)
}

// save writes the current configuration to disk (must be called with lock held)
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

// GetMetricsGrid returns the metrics grid configuration
func (m *ConfigManager) GetMetricsGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.MetricsGrid.Rows, m.config.MetricsGrid.Cols
}

// SetMetricsRows sets the metrics grid rows
func (m *ConfigManager) SetMetricsRows(rows int) error {
	if rows < 1 || rows > 9 {
		return nil // silently ignore invalid values
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Rows = rows
	return m.save()
}

// SetMetricsCols sets the metrics grid columns
func (m *ConfigManager) SetMetricsCols(cols int) error {
	if cols < 1 || cols > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.MetricsGrid.Cols = cols
	return m.save()
}

// GetSystemGrid returns the system grid configuration
func (m *ConfigManager) GetSystemGrid() (rows, cols int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.SystemGrid.Rows, m.config.SystemGrid.Cols
}

// SetSystemRows sets the system grid rows
func (m *ConfigManager) SetSystemRows(rows int) error {
	if rows < 1 || rows > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Rows = rows
	return m.save()
}

// SetSystemCols sets the system grid columns
func (m *ConfigManager) SetSystemCols(cols int) error {
	if cols < 1 || cols > 9 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.config.SystemGrid.Cols = cols
	return m.save()
}

// GetColorScheme returns the current color scheme
func (m *ConfigManager) GetColorScheme() string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.ColorScheme
}
