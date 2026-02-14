package filetransfer

import (
	"errors"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSafeJoinPath(t *testing.T) {
	const basePath = "/tmp/downloads"

	tests := []struct {
		name              string
		untrustedRelative string
		wantPath          string
		wantErr           error
	}{
		{
			name:              "simple relative path",
			untrustedRelative: "file.txt",
			wantPath:          filepath.Join(basePath, "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "nested relative path",
			untrustedRelative: "subdir/file.txt",
			wantPath:          filepath.Join(basePath, "subdir", "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "deeply nested path",
			untrustedRelative: "a/b/c/d/file.txt",
			wantPath:          filepath.Join(basePath, "a", "b", "c", "d", "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "empty relative path returns base",
			untrustedRelative: "",
			wantPath:          basePath,
			wantErr:           nil,
		},
		{
			name:              "path traversal with ../",
			untrustedRelative: "../../../etc/passwd",
			wantPath:          "",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "path traversal at start",
			untrustedRelative: "../secret.txt",
			wantPath:          "",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "path traversal in middle",
			untrustedRelative: "subdir/../../../etc/passwd",
			wantPath:          "",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "path traversal escaping after valid prefix",
			untrustedRelative: "valid/path/../../../../etc/shadow",
			wantPath:          "",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "absolute path on unix",
			untrustedRelative: "/etc/passwd",
			wantPath:          "",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "forward slashes converted correctly",
			untrustedRelative: "path/to/file.txt",
			wantPath:          filepath.Join(basePath, "path", "to", "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "current directory reference is safe",
			untrustedRelative: "./file.txt",
			wantPath:          filepath.Join(basePath, "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "double dot in filename is safe",
			untrustedRelative: "file..txt",
			wantPath:          filepath.Join(basePath, "file..txt"),
			wantErr:           nil,
		},
		{
			name:              "triple dot is safe",
			untrustedRelative: ".../file.txt",
			wantPath:          filepath.Join(basePath, "...", "file.txt"),
			wantErr:           nil,
		},
		{
			name:              "dot dot dot is safe",
			untrustedRelative: "...",
			wantPath:          filepath.Join(basePath, "..."),
			wantErr:           nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotPath, gotErr := SafeJoinPath(basePath, tt.untrustedRelative)

			if tt.wantErr != nil {
				require.Error(t, gotErr)
				assert.True(t, errors.Is(gotErr, tt.wantErr),
					"expected error %v, got %v", tt.wantErr, gotErr)
				assert.Empty(t, gotPath)
			} else {
				require.NoError(t, gotErr)
				assert.Equal(t, tt.wantPath, gotPath)
			}
		})
	}
}

func TestSafeJoinPath_WindowsSpecific(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("Windows-specific tests")
	}

	const basePath = "C:\\downloads"

	tests := []struct {
		name              string
		untrustedRelative string
		wantErr           error
	}{
		{
			name:              "windows absolute path",
			untrustedRelative: "C:\\Windows\\System32\\config\\SAM",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "windows UNC path",
			untrustedRelative: "\\\\server\\share\\file.txt",
			wantErr:           ErrPathTraversal,
		},
		{
			name:              "backslash traversal",
			untrustedRelative: "..\\..\\Windows\\System32",
			wantErr:           ErrPathTraversal,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, gotErr := SafeJoinPath(basePath, tt.untrustedRelative)
			if tt.wantErr != nil {
				require.Error(t, gotErr)
				assert.True(t, errors.Is(gotErr, tt.wantErr))
			}
		})
	}
}

// TestSafeJoinPath_RealWorldAttackVectors tests actual attack patterns
// that could be used in cloud storage object names.
func TestSafeJoinPath_RealWorldAttackVectors(t *testing.T) {
	const basePath = "/home/user/.wandb/artifacts"

	attackVectors := []struct {
		name       string
		objectName string
		wantErr    bool
	}{
		{
			name:       "SSH key overwrite",
			objectName: "../../../.ssh/authorized_keys",
			wantErr:    true,
		},
		{
			name:       "cron job injection",
			objectName: "../../../etc/cron.d/malicious",
			wantErr:    true,
		},
		{
			name:       "bashrc modification",
			objectName: "../../../.bashrc",
			wantErr:    true,
		},
		{
			name:       "systemd service injection",
			objectName: "../../../etc/systemd/system/backdoor.service",
			wantErr:    true,
		},
		{
			name:       "python package injection",
			objectName: "../../../.local/lib/python3.10/site-packages/malicious.py",
			wantErr:    true,
		},
		{
			name:       "legitimate nested artifact",
			objectName: "model/weights/layer1.bin",
			wantErr:    false,
		},
		{
			name:       "legitimate file with dots",
			objectName: "model.v2.0.weights",
			wantErr:    false,
		},
	}

	for _, tt := range attackVectors {
		t.Run(tt.name, func(t *testing.T) {
			_, err := SafeJoinPath(basePath, tt.objectName)
			if tt.wantErr {
				assert.Error(t, err, "expected attack vector to be blocked: %s", tt.objectName)
				assert.True(t, errors.Is(err, ErrPathTraversal))
			} else {
				assert.NoError(t, err, "expected legitimate path to be allowed: %s", tt.objectName)
			}
		})
	}
}

// TestSafeJoinPath_CloudStoragePatterns tests patterns commonly seen
// in cloud storage object keys.
func TestSafeJoinPath_CloudStoragePatterns(t *testing.T) {
	const basePath = "/tmp/artifacts"
	const prefix = "artifacts/v1/"

	tests := []struct {
		name      string
		objectKey string
		wantErr   bool
	}{
		{
			name:      "S3-style prefix stripping - normal",
			objectKey: prefix + "model.bin",
			wantErr:   false,
		},
		{
			name:      "S3-style prefix stripping - nested",
			objectKey: prefix + "subdir/model.bin",
			wantErr:   false,
		},
		{
			name:      "Malicious key - different prefix with traversal",
			objectKey: "malicious/../../../etc/passwd",
			wantErr:   true,
		},
		{
			name:      "Malicious key - prefix doesn't match",
			objectKey: "other/path/../../../etc/passwd",
			wantErr:   true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate what the cloud file transfers do
			relativePath, _ := strings.CutPrefix(tt.objectKey, prefix)
			_, err := SafeJoinPath(basePath, relativePath)

			if tt.wantErr {
				assert.Error(t, err)
				assert.True(t, errors.Is(err, ErrPathTraversal))
			} else {
				assert.NoError(t, err)
			}
		})
	}
}
