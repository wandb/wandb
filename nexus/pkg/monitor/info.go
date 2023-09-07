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

// Helper function to copy a file
func copyFile(src, dst string) error {
	source, err := os.Open(src)
	if err != nil {
		return err
	}
	defer source.Close()

	destination, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destination.Close()

	_, err = io.Copy(destination, source)
	if err != nil {
		return err
	}
	return nil
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
	files := service.FilesRecord{
		Files: []*service.FilesItem{
			{
				Path: filepath.Join("code", programRelative),
			},
		},
	}
	return &files, nil
}

func (si *SystemInfo) GetFileInfo() *service.Record {

	if si.settings.GetSaveCode().GetValue() {
		fileItem, err := si.saveCode()
		if err != nil {
			return nil
		}
		if fileItem != nil {
			record := service.Record{
				RecordType: &service.Record_Files{
					Files: fileItem,
				},
			}
			return &record
		}
	}
	return nil
}

func (si *SystemInfo) GetMetadata() *service.Record {
	if si.settings.GetXDisableMeta().GetValue() {
		return nil
	}
	record := service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_Metadata{
					Metadata: &service.MetadataRequest{
						Os:            si.settings.GetXOs().GetValue(),
						Python:        si.settings.GetXPython().GetValue(),
						Host:          si.settings.GetHost().GetValue(),
						Cuda:          si.settings.GetXCuda().GetValue(),
						Program:       si.settings.GetProgram().GetValue(),
						CodePath:      si.settings.GetProgram().GetValue(),
						CodePathLocal: si.settings.GetProgram().GetValue(),
						Email:         si.settings.GetEmail().GetValue(),
						Root:          si.settings.GetRootDir().GetValue(),
						Username:      si.settings.GetUsername().GetValue(),
						Docker:        si.settings.GetDocker().GetValue(),
						Executable:    si.settings.GetXExecutable().GetValue(),
						Args:          si.settings.GetXArgs().GetValue(),
						// StartedAt:     si.settings.GetXStartTime().GetValue(),
					},
				},
			},
		},
	}
	return &record
}
