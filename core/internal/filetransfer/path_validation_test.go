package filetransfer

import (
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

const basePath = "/tmp/downloads"

func TestSafeJoinPath(t *testing.T) {
	tests := []struct {
		name               string
		relativePath       string
		expectedJoinedPath string
		expectedErr        bool
	}{
		{
			name:               "simple relative path",
			relativePath:       "file.txt",
			expectedJoinedPath: filepath.Join(basePath, "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "nested relative path",
			relativePath:       "subdir/file.txt",
			expectedJoinedPath: filepath.Join(basePath, "subdir", "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "deeply nested path",
			relativePath:       "a/b/c/d/file.txt",
			expectedJoinedPath: filepath.Join(basePath, "a", "b", "c", "d", "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "empty relative path returns base",
			relativePath:       "",
			expectedJoinedPath: basePath,
			expectedErr:        false,
		},
		{
			name:               "path traversal with ../",
			relativePath:       "../../../etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "path traversal at start",
			relativePath:       "../secret.txt",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "path traversal in middle",
			relativePath:       "subdir/../../../etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "path traversal escaping after valid prefix",
			relativePath:       "valid/path/../../../../etc/shadow",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "absolute path on unix",
			relativePath:       "/etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "forward slashes converted correctly",
			relativePath:       "path/to/file.txt",
			expectedJoinedPath: filepath.Join(basePath, "path", "to", "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "current directory reference",
			relativePath:       "./file.txt",
			expectedJoinedPath: filepath.Join(basePath, "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "double dot in filename",
			relativePath:       "file..txt",
			expectedJoinedPath: filepath.Join(basePath, "file..txt"),
			expectedErr:        false,
		},
		{
			name:               "triple dot directory name",
			relativePath:       ".../file.txt",
			expectedJoinedPath: filepath.Join(basePath, "...", "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "triple dot as filename",
			relativePath:       "...",
			expectedJoinedPath: filepath.Join(basePath, "..."),
			expectedErr:        false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			safelyJoinedPath, err := SafeJoinPath(basePath, tt.relativePath)

			if tt.expectedErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrPathTraversal)
				assert.Empty(t, safelyJoinedPath)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedJoinedPath, safelyJoinedPath)
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
		name               string
		relativePath       string
		expectedJoinedPath string
		expectedErr        bool
	}{
		// Positive cases
		{
			name:               "simple file in base directory",
			relativePath:       "file.txt",
			expectedJoinedPath: filepath.Join(basePath, "file.txt"),
			expectedErr:        false,
		},
		{
			name:               "nested subdirectory",
			relativePath:       "models\\v1\\weights.bin",
			expectedJoinedPath: filepath.Join(basePath, "models", "v1", "weights.bin"),
			expectedErr:        false,
		},
		{
			name:               "file with spaces",
			relativePath:       "my models\\best model.bin",
			expectedJoinedPath: filepath.Join(basePath, "my models", "best model.bin"),
			expectedErr:        false,
		},
		{
			name:               "file with dots in name",
			relativePath:       "model.v2.0.weights",
			expectedJoinedPath: filepath.Join(basePath, "model.v2.0.weights"),
			expectedErr:        false,
		},
		// Negative cases
		{
			name:               "windows absolute path",
			relativePath:       "C:\\Windows\\System32\\config\\SAM",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "windows UNC path",
			relativePath:       "\\\\server\\share\\file.txt",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "backslash traversal",
			relativePath:       "..\\..\\Windows\\System32",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "mixed slash traversal",
			relativePath:       "..\\../..\\etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "drive letter with different case",
			relativePath:       "d:\\Users\\Public\\malware.exe",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			safelyJoinedPath, err := SafeJoinPath(basePath, tt.relativePath)
			if tt.expectedErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrPathTraversal)
				assert.Empty(t, safelyJoinedPath)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedJoinedPath, safelyJoinedPath)
			}
		})
	}
}

// TestSafeJoinPath_RealWorldAttackVectors tests actual attack patterns
// that could be used in cloud storage object names.
func TestSafeJoinPath_RealWorldAttackVectors(t *testing.T) {
	tests := []struct {
		name               string
		relativePath       string
		expectedJoinedPath string
		expectedErr        bool
	}{
		{
			name:               "SSH key overwrite",
			relativePath:       "../../../.ssh/authorized_keys",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "cron job injection",
			relativePath:       "../../../etc/cron.d/malicious",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "bashrc modification",
			relativePath:       "../../../.bashrc",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "systemd service injection",
			relativePath:       "../../../etc/systemd/system/backdoor.service",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "python package injection",
			relativePath:       "../../../.local/lib/python3.10/site-packages/malicious.py",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "git config overwrite",
			relativePath:       "../../../.gitconfig",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "kubeconfig overwrite",
			relativePath:       "../../../.kube/config",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "AWS credentials theft",
			relativePath:       "../../../.aws/credentials",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "legitimate nested artifact",
			relativePath:       "model/weights/layer1.bin",
			expectedJoinedPath: filepath.Join(basePath, "model", "weights", "layer1.bin"),
			expectedErr:        false,
		},
		{
			name:               "legitimate file with dots",
			relativePath:       "model.v2.0.weights",
			expectedJoinedPath: filepath.Join(basePath, "model.v2.0.weights"),
			expectedErr:        false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			safelyJoinedPath, err := SafeJoinPath(basePath, tt.relativePath)
			if tt.expectedErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrPathTraversal)
				assert.Empty(t, safelyJoinedPath)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedJoinedPath, safelyJoinedPath)
			}
		})
	}
}

// TestSafeJoinPath_CloudStoragePatterns tests patterns commonly seen
// in cloud storage object keys after prefix stripping.
func TestSafeJoinPath_CloudStoragePatterns(t *testing.T) {
	const prefix = "artifacts/v1/"

	tests := []struct {
		name               string
		objectKey          string
		expectedJoinedPath string
		expectedErr        bool
	}{
		{
			name:               "S3-style prefix stripping - normal",
			objectKey:          prefix + "model.bin",
			expectedJoinedPath: filepath.Join(basePath, "model.bin"),
			expectedErr:        false,
		},
		{
			name:               "S3-style prefix stripping - nested",
			objectKey:          prefix + "subdir/model.bin",
			expectedJoinedPath: filepath.Join(basePath, "subdir", "model.bin"),
			expectedErr:        false,
		},
		{
			name:               "malicious key - different prefix with traversal",
			objectKey:          "malicious/../../../etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "malicious key - prefix doesn't match",
			objectKey:          "other/path/../../../etc/passwd",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
		{
			name:               "key exactly matching prefix yields empty relative path",
			objectKey:          prefix,
			expectedJoinedPath: basePath,
			expectedErr:        false,
		},
		{
			name:               "traversal embedded after valid prefix",
			objectKey:          prefix + "subdir/../../../etc/shadow",
			expectedJoinedPath: "",
			expectedErr:        true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate what the cloud file transfers do:
			// strip the expected prefix, then validate the remainder.
			relativePath, _ := strings.CutPrefix(tt.objectKey, prefix)
			safelyJoinedPath, err := SafeJoinPath(basePath, relativePath)

			if tt.expectedErr {
				require.Error(t, err)
				assert.ErrorIs(t, err, ErrPathTraversal)
				assert.Empty(t, safelyJoinedPath)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expectedJoinedPath, safelyJoinedPath)
			}
		})
	}
}
