package monitor

import (
	"fmt"
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

func (s *SystemInfo) saveCode() (*string, error) {
	root := s.settings.GetRootDir().GetValue()
	programRelative := s.settings.GetProgramRelpath().GetValue()
	filesDir := s.settings.GetFilesDir().GetValue()
	codeDir := filepath.Join(filesDir, "code", filepath.Dir(programRelative))
	if err := os.MkdirAll(codeDir, os.ModePerm); err != nil {
		return nil, err
	}
	programAbsolute := filepath.Join(root, programRelative)
	_, err := os.Stat(programAbsolute)
	if err != nil {
		return nil, err
	}
	savedProgram := filepath.Join(filesDir, "code", programRelative)
	_, err = os.Stat(savedProgram)
	if err != nil {
		if err := copyFile(programAbsolute, savedProgram); err != nil {
			return nil, err
		}
	}
	return &programRelative, nil
}

func (s *SystemInfo) GetInfo() (*service.Record, error) {
	if s.settings.GetSaveCode().GetValue() {
		record := service.Record{
			RecordType: &service.Record_Files{
				Files: &service.FilesRecord{},
			},
		}
		if program, err := s.saveCode(); err != nil {
			return nil, err
		} else {
			savedProgram := filepath.Join("code", *program)
			fileItem := []*service.FilesItem{
				{
					Path:   savedProgram,
					Policy: service.FilesItem_NOW,
				},
			}
			fmt.Println(fileItem)
			// files.Files = append(files.Files, fileItem...)
			record.RecordType.(*service.Record_Files).Files.Files = append(
				record.RecordType.(*service.Record_Files).Files.Files,
				fileItem...,
			)
		}
		return &record, nil
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
