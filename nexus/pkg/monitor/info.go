package monitor

import (
	"io"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type SystemInfo struct {
	settings *service.Settings
	Metadata *service.MetadataRequest
}

func NewSystemInfo(settings *service.Settings) *SystemInfo {
	return &SystemInfo{
		settings: settings,
		Metadata: &service.MetadataRequest{
			Os:            settings.GetXOs().GetValue(),
			Python:        settings.GetXPython().GetValue(),
			Host:          settings.GetHost().GetValue(),
			Cuda:          settings.GetXCuda().GetValue(),
			Program:       settings.GetProgram().GetValue(),
			CodePath:      settings.GetProgram().GetValue(),
			CodePathLocal: settings.GetProgram().GetValue(),
			Email:         settings.GetEmail().GetValue(),
			Root:          settings.GetRootDir().GetValue(),
			Username:      settings.GetUsername().GetValue(),
			Docker:        settings.GetDocker().GetValue(),
			Executable:    settings.GetXExecutable().GetValue(),
			Args:          settings.GetXArgs().GetValue(),
		},
	}
}

func (si *SystemInfo) saveCode() (*service.FilesRecord, error) {
	rootDir := si.settings.GetRootDir().GetValue()
	programRelative := si.settings.GetProgramRelpath().GetValue()
	programAbsolute := filepath.Join(rootDir, programRelative)
	if _, err := os.Stat(programAbsolute); err != nil {
		return nil, err
	}

	filesDir := si.settings.GetFilesDir().GetValue()
	codeDir := filepath.Join(filesDir, "code", filepath.Dir(programRelative))
	if err := os.MkdirAll(codeDir, os.ModePerm); err != nil {
		return nil, err
	}
	savedProgram := filepath.Join(filesDir, "code", programRelative)
	if _, err := os.Stat(savedProgram); err != nil {
		if err = copyFile(programAbsolute, savedProgram); err != nil {
			return nil, err
		}
	}
	path := filepath.Join("code", programRelative)
	file := &service.FilesItem{
		Path: path,
	}
	files := service.FilesRecord{
		Files: []*service.FilesItem{file},
	}
	return &files, nil
}

func (si *SystemInfo) GetInfo() (*service.Record, error) {

	if si.settings.GetSaveCode().GetValue() {
		fileItem, err := si.saveCode()
		if err != nil {
			return nil, err
		}
		if fileItem != nil {
			record := service.Record{
				RecordType: &service.Record_Files{
					Files: fileItem,
				},
			}
			return &record, nil
		}
	}
	return nil, nil
}

// Helper function to copy a file
func copyFile(src, dst string) error {
	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destinationFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destinationFile.Close()

	_, err = io.Copy(destinationFile, sourceFile)
	if err != nil {
		return err
	}
	return nil
}
