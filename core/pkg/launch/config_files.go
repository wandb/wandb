package launch

import (
	"fmt"
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

func (j *JobBuilder) HandleConfigFileParameterRecord(configFileParameter *service.LaunchConfigFileParameterRecord) {
	j.saveShapeToMetadata = true
	j.configFiles = append(
		j.configFiles, newConfigParameterFromRecord(configFileParameter),
	)
}
