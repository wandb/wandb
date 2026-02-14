package settings

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func setEnv(t *testing.T, key, value string) {
	t.Helper()
	original := os.Getenv(key)
	err := os.Setenv(key, value)
	if err != nil {
		t.Fatalf("Failed to set environment variable %s: %v", key, err)
	}

	t.Cleanup(func() {
		if original == "" {
			os.Unsetenv(key)
		} else {
			os.Setenv(key, original)
		}
	})
}

func TestLoadSettings_ApiKeyEnvVariable(t *testing.T) {
	testAPIKey := "test_api_key_12345"
	setEnv(t, "WANDB_API_KEY", testAPIKey)

	settings, err := LoadSettings()
	require.NoError(t, err)

	assert.Equal(t, testAPIKey, settings.GetAPIKey())
}

func TestLoadSettings_BaseURLEnvVariable(t *testing.T) {
	// Save and restore original environment
	testBaseURL := "https://custom.wandb.ai"
	setEnv(t, "WANDB_BASE_URL", testBaseURL)

	settings, err := LoadSettings()
	require.NoError(t, err)

	assert.Equal(t, testBaseURL, settings.GetBaseURL())
}

func TestLoadSettings_DefaultBaseURL(t *testing.T) {
	tempDir := t.TempDir()
	setEnv(t, "WANDB_CONFIG_DIR", tempDir)
	settings, err := LoadSettings()
	require.NoError(t, err)

	expectedBaseURL := "https://api.wandb.ai"
	assert.Equal(t, expectedBaseURL, settings.GetBaseURL())
}

func TestReadSettingsFile(t *testing.T) {
	// Create a temporary settings file
	tmpDir := t.TempDir()
	settingsPath := filepath.Join(tmpDir, "settings")

	settingsContent := `
		[default]
		base_url = https://custom.wandb.ai
	`
	err := os.WriteFile(settingsPath, []byte(settingsContent), 0o600)
	require.NoError(t, err)
	setEnv(t, "WANDB_CONFIG_DIR", tmpDir)

	settings, err := readSettingsFile()
	require.NoError(t, err)

	expectedSettings := map[string]string{
		"base_url": "https://custom.wandb.ai",
	}
	assert.Equal(t, expectedSettings, settings)
}

func TestLoadSettings_EnvOverridesSettingsFile(t *testing.T) {
	// Create a temporary settings file
	tmpDir := t.TempDir()
	settingsPath := filepath.Join(tmpDir, "settings")

	settingsContent := `[default]
		base_url = https://settings-file.wandb.ai
	`
	err := os.WriteFile(settingsPath, []byte(settingsContent), 0o600)
	require.NoError(t, err)
	setEnv(t, "WANDB_CONFIG_DIR", tmpDir)
	setEnv(t, "WANDB_BASE_URL", "https://env-override.wandb.ai")

	settings, err := LoadSettings()
	require.NoError(t, err)

	assert.Equal(t, "https://env-override.wandb.ai", settings.GetBaseURL())
}

func TestLoadSettings_NetrcAPIKey(t *testing.T) {
	setEnv(t, "WANDB_API_KEY", "")
	netrcPath := filepath.Join(t.TempDir(), "netrc")
	netrcContent := `
		machine api.wandb.ai
		password test_api_key_12345
	`
	err := os.WriteFile(netrcPath, []byte(netrcContent), 0o644)
	require.NoError(t, err)
	setEnv(t, "NETRC", netrcPath)

	tmpDir := t.TempDir()
	settingsPath := filepath.Join(tmpDir, "settings")

	settingsContent := `[default]
		base_url = https://api.wandb.ai
	`
	err = os.WriteFile(settingsPath, []byte(settingsContent), 0o644)
	require.NoError(t, err)
	setEnv(t, "WANDB_CONFIG_DIR", tmpDir)

	settings, err := LoadSettings()
	require.NoError(t, err)
	assert.Equal(t, "test_api_key_12345", settings.GetAPIKey())
}

func TestLoadSettings_ApiKeyOverridesNetrc(t *testing.T) {
	netrcPath := filepath.Join(t.TempDir(), "netrc")
	netrcContent := `
		machine api.wandb.ai
		password test_api_key_12345
	`
	err := os.WriteFile(netrcPath, []byte(netrcContent), 0o644)
	require.NoError(t, err)
	setEnv(t, "NETRC", netrcPath)
	setEnv(t, "WANDB_API_KEY", "test_api_key_45678")

	settings, err := LoadSettings()
	require.NoError(t, err)
	assert.Equal(t, "test_api_key_45678", settings.GetAPIKey())
}

func TestExpandHome(t *testing.T) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		t.Skipf("Cannot get home directory: %v", err)
	}

	tests := []struct {
		name  string
		path  string
		want  string
		check func(got, want string) bool
	}{
		{
			name: "tilde only",
			path: "~",
			want: homeDir,
			check: func(got, want string) bool {
				return got == want
			},
		},
		{
			name: "tilde with path",
			path: "~/.config",
			want: filepath.Join(homeDir, ".config"),
			check: func(got, want string) bool {
				return got == want
			},
		},
		{
			name: "no tilde",
			path: "/absolute/path",
			want: "/absolute/path",
			check: func(got, want string) bool {
				return got == want
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := expandHome(tt.path)
			if !tt.check(got, tt.want) {
				t.Errorf("expandHome(%q) = %v, want %v", tt.path, got, tt.want)
			}
		})
	}
}
