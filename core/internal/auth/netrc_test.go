package auth_test

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/wandb/wandb/core/internal/auth"
)

func TestNetrcPath(t *testing.T) {
	// Save original environment and restore it after the test
	origEnv := os.Getenv("NETRC")
	origHome := os.Getenv("HOME")
	defer func() {
		os.Setenv("NETRC", origEnv)
		os.Setenv("HOME", origHome)
	}()

	t.Run("NETRC environment variable set", func(t *testing.T) {
		os.Setenv("NETRC", "/custom/path/.netrc")
		path, err := auth.NetrcPath()
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if path != "/custom/path/.netrc" {
			t.Errorf("Expected path %s, got %s", "/custom/path/.netrc", path)
		}
	})

	t.Run("Home directory not found", func(t *testing.T) {
		os.Setenv("NETRC", "")
		os.Setenv("HOME", "")
		_, err := auth.NetrcPath()
		if err == nil {
			t.Error("Expected error, got nil")
		}
	})

	t.Run("Existing .netrc file", func(t *testing.T) {
		tempDir := t.TempDir()
		os.Setenv("HOME", tempDir)
		os.Setenv("NETRC", "")

		netrcPath := filepath.Join(tempDir, ".netrc")
		_, err := os.Create(netrcPath)
		if err != nil {
			t.Fatalf("Failed to create test file: %v", err)
		}

		path, err := auth.NetrcPath()
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if path != netrcPath {
			t.Errorf("Expected path %s, got %s", netrcPath, path)
		}
	})

	t.Run("Existing _netrc file", func(t *testing.T) {
		tempDir := t.TempDir()
		os.Setenv("HOME", tempDir)
		os.Setenv("NETRC", "")

		netrcPath := filepath.Join(tempDir, "_netrc")
		_, err := os.Create(netrcPath)
		if err != nil {
			t.Fatalf("Failed to create test file: %v", err)
		}

		path, err := auth.NetrcPath()
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if path != netrcPath {
			t.Errorf("Expected path %s, got %s", netrcPath, path)
		}
	})

	t.Run("No existing netrc file", func(t *testing.T) {
		tempDir := t.TempDir()
		os.Setenv("HOME", tempDir)
		os.Setenv("NETRC", "")

		path, err := auth.NetrcPath()
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}

		expectedBase := ".netrc"
		if runtime.GOOS == "windows" {
			expectedBase = "_netrc"
		}
		expectedPath := filepath.Join(tempDir, expectedBase)

		if path != expectedPath {
			t.Errorf("Expected path %s, got %s", expectedPath, path)
		}
	})
}
