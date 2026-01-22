package fileutil_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/fileutil"
)

func TestSanitizeLinuxFilename(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"valid-filename", "valid-filename"}, // Valid filename
		{
			"file/with/slash",
			"file_with_slash",
		}, // Slash replaced with underscore
		{
			"file\x00with\x00null",
			"file_with_null",
		}, // Null characters replaced with underscore
		{"file with leading space ", "file with leading space"}, // Leading space trimmed
		{
			" file with trailing space ",
			"file with trailing space",
		}, // Leading and trailing space trimmed
		{"file....", "file"},                 // Trailing dots trimmed
		{"control\x07chars", "controlchars"}, // Control characters removed
		{"", ""},                             // Empty string
		{
			" . ..hidden file.",
			". ..hidden file",
		}, // Leading dot treated as valid
		{"filename....with....dots....", "filename....with....dots"}, // Internal dots preserved
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			output := fileutil.SanitizeLinuxFilename(tt.input)
			if output != tt.expected {
				t.Errorf("SanitizeLinuxFilename(%q) = %q, want %q", tt.input, output, tt.expected)
			}
		})
	}
}

func TestSanitizeWindowsFilename(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"valid-filename.txt", "valid-filename.txt"}, // Valid filename
		{
			"invalid<file>name",
			"invalid_file_name",
		}, // Forbidden characters replaced
		{
			"trailing space ",
			"trailing space",
		}, // Trailing space trimmed
		{"trailing.dot.", "trailing.dot"}, // Trailing dot trimmed
		{
			"<:>?|*\"\\filename",
			"________filename",
		}, // Multiple forbidden characters
		{
			"CON",
			"CON_safe",
		}, // Reserved name (case-sensitive)
		{
			"nul",
			"nul_safe",
		}, // Reserved name (case-insensitive)
		{"COM1", "COM1_safe"}, // Reserved name
		{
			"filename with trailing dots....",
			"filename with trailing dots",
		}, // Multiple trailing dots
		{" ", ""},              // Only space
		{".", ""},              // Only dot
		{"AUX.log", "AUX.log"}, // Reserved name but with extension
		{"", ""},               // Empty string
	}

	for _, test := range tests {
		t.Run(test.input, func(t *testing.T) {
			result := fileutil.SanitizeWindowsFilename(test.input)
			if result != test.expected {
				t.Errorf(
					"SanitizeWindowsFilename(%q) = %q; want %q",
					test.input,
					result,
					test.expected,
				)
			}
		})
	}
}

func TestCreateUnique(t *testing.T) {
	basePath := filepath.Join(t.TempDir(), "my-file")

	file1, err := fileutil.CreateUnique(basePath, "txt", 0o644)
	require.NoError(t, err)
	require.NoError(t, file1.Close())

	file2, err := fileutil.CreateUnique(basePath, "txt", 0o644)
	require.NoError(t, err)
	require.NoError(t, file2.Close())

	file3, err := fileutil.CreateUnique(basePath, "txt", 0o644)
	require.NoError(t, err)
	require.NoError(t, file3.Close())

	assert.Equal(t, "my-file.txt", filepath.Base(file1.Name()))
	assert.Equal(t, "my-file.1.txt", filepath.Base(file2.Name()))
	assert.Equal(t, "my-file.2.txt", filepath.Base(file3.Name()))
}
