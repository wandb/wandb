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

func newFileInputFromRequest(
	request *service.JobInputRequest,
) (*configFileParameter, error) {
	source := request.GetInputSource().GetSource()
	file, ok := source.(*service.JobInputSource_File)
	if !ok {
		return nil, fmt.Errorf("jobBuilder: invalid source type for file input")
	}

	includePaths := make([]ConfigPath, 0, len(request.GetIncludePaths()))
	for _, path := range request.GetIncludePaths() {
		includePaths = append(includePaths, ConfigPath(path.Path))
	}

	excludePaths := make([]ConfigPath, 0, len(request.GetExcludePaths()))
	for _, path := range request.GetExcludePaths() {
		excludePaths = append(excludePaths, ConfigPath(path.Path))
	}

	return &configFileParameter{
		relpath:      file.File.GetPath(),
		includePaths: includePaths,
		excludePaths: excludePaths,
	}, nil
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
	return data_types.ResolveTypes((config.filterTree(
		configFile.includePaths, configFile.excludePaths,
	)))
}
