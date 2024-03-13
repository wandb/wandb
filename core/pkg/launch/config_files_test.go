package launch_test

import (
	"os"
	"path/filepath"
	"testing"

	. "github.com/wandb/wandb/core/pkg/launch"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestWriteAndSaveConfigFile(t *testing.T) {
	sourcePath := "test_source.yaml"
	filesDir := "test_files_dir"
	tempDir := filepath.Join(os.TempDir(), "test")
	err := os.MkdirAll(tempDir, 0755)
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	writeFile(t, tempDir, sourcePath, "test content")
	err = os.Chdir(tempDir)
	if err != nil {
		t.Fatalf("Failed to change to temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	record, err := WriteAndSaveConfigFile(sourcePath, filesDir)
	if err != nil {
		t.Fatalf("WriteAndSaveConfigFile failed: %v", err)
	}

	expectedPath := filepath.Join("configs", sourcePath)
	if record.RecordType == nil || record.RecordType.(*service.Record_Files) == nil {
		t.Fatalf("Unexpected record type: %v", record.RecordType)
	}
	filesRecord := record.RecordType.(*service.Record_Files).Files
	if len(filesRecord.Files) != 1 {
		t.Fatalf("Unexpected number of files in record: %d", len(filesRecord.Files))
	}
	if filesRecord.Files[0].Path != expectedPath {
		t.Fatalf("Unexpected file path in record: %s", filesRecord.Files[0].Path)
	}
	if filesRecord.Files[0].Type != service.FilesItem_WANDB {
		t.Fatalf("Unexpected file type in record: %v", filesRecord.Files[0].Type)
	}

	// Verify the created config file
	configFile := filepath.Join(filesDir, expectedPath)
	_, err = os.Stat(configFile)
	if err != nil {
		t.Fatalf("Failed to find created config file: %v", err)
	}
}
