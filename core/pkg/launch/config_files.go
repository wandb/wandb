package launch

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/data_types"
	"github.com/wandb/wandb/core/pkg/service"
)

// Represents a config file parameter for a job.
//
// The relpath is the path to the config file relative to the files directory.
// The includePaths and excludePaths are used to filter down the run config
// before it is converted to a schema and saved as job inputs.
type configFileParameter struct {
	relpath      string
	includePaths []ConfigPath
	excludePaths []ConfigPath
}

func newConfigParameterFromRecord(record *service.LaunchConfigFileParameterRecord) *configFileParameter {
	includePaths := make([]ConfigPath, len(record.GetIncludePaths()))
	excludePaths := make([]ConfigPath, len(record.GetExcludePaths()))
	for i, path := range record.GetIncludePaths() {
		includePaths[i] = ConfigPath(path.Path)
	}
	for i, path := range record.GetExcludePaths() {
		excludePaths[i] = ConfigPath(path.Path)
	}
	return &configFileParameter{record.GetRelpath(), includePaths, excludePaths}
}

// Infers the structure of a config file.
//
// This returns the tree structure and data types of the given config file after filtering
// its subtrees according to the 'include' and 'exclude' paths in the record.
func (j *JobBuilder) generateConfigFileSchema(
	configFile *configFileParameter,
) data_types.TypeRepresentation {
	path := filepath.Join(j.settings.FilesDir.GetValue(), "configs", configFile.relpath)
	config, err := deserializeConfig(path)
	if err != nil {
		j.logger.Error("jobBuilder: error creating runconfig from config file", err)
		return data_types.TypeRepresentation{}
	}
	fmt.Println(config.tree, configFile.includePaths, configFile.excludePaths)
	fmt.Println(config.filterTree(configFile.includePaths, configFile.excludePaths))
	return data_types.ResolveTypes((config.filterTree(
		configFile.includePaths, configFile.excludePaths,
	)))
}

// Write config to files directory and return a record for the file handler.
//
// sourcePath is a relative path to the config file from the current working directory.
// filesDir is the directory where the config file will be saved, assumed to be
// a run files directory. sourcePath can not have any backwards path traversal.
//
// We save this file to the run so that we know what values this run used
// for the corresponding job inputs.
func WriteAndSaveConfigFile(
	sourcePath, filesDir string,
) (*service.Record, error) {
	configDir := filepath.Join(filesDir, "configs")
	if err := os.MkdirAll(configDir, os.ModePerm); err != nil {
		return nil, err
	}
	source, err := os.Open(sourcePath)
	if err != nil {
		defer source.Close()
		return nil, err
	}
	defer source.Close()
	configFile := filepath.Join(configDir, sourcePath)
	destination, err := os.Create(configFile)
	if err != nil {
		defer destination.Close()
		return nil, err
	}
	if _, err := io.Copy(destination, source); err != nil {
		return nil, err
	}
	defer destination.Close()
	return &service.Record{
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: []*service.FilesItem{
					{
						Path: filepath.Join("configs", sourcePath),
						Type: service.FilesItem_WANDB,
					},
				},
			},
		},
	}, nil
}

func (j *JobBuilder) HandleConfigFileParameterRecord(configFileParameter *service.LaunchConfigFileParameterRecord) {
	j.saveShapeToMetadata = true
	j.configFiles = append(
		j.configFiles, newConfigParameterFromRecord(configFileParameter),
	)
}
