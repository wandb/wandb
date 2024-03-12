package launch

import (
	"github.com/wandb/wandb/core/internal/data_types"
	"github.com/wandb/wandb/core/pkg/service"
)

func (j *JobBuilder) getWandbConfigInputs() data_types.TypeRepresentation {
	include, exclude := j.getWandbConfigFilters()
	config := NewConfigFrom(j.runConfig.CloneTree())
	return data_types.ResolveTypes(config.FilterTree(include, exclude))
}

// Converts received LaunchWandbConfigParametersRecords into include and exclude paths.
func (j *JobBuilder) getWandbConfigFilters() ([]ConfigPath, []ConfigPath) {
	include := make([]ConfigPath, 0)
	exclude := make([]ConfigPath, 0)
	if len(j.wandbConfigParameters) > 0 {
		for _, wandbConfigParameters := range j.wandbConfigParameters {
			if wandbConfigParameters.IncludePaths != nil {
				for _, includePath := range wandbConfigParameters.IncludePaths {
					include = append(include, includePath.Path)
				}
			}
			if wandbConfigParameters.ExcludePaths != nil {
				for _, excludePath := range wandbConfigParameters.ExcludePaths {
					exclude = append(exclude, excludePath.Path)
				}
			}
		}
	}
	return include, exclude
}

func (j *JobBuilder) HandleLaunchWandbConfigParametersRecord(wandbConfigParameters *service.LaunchWandbConfigParametersRecord) {
	j.saveShapeToMetadata = true
	j.wandbConfigParameters = append(j.wandbConfigParameters, wandbConfigParameters)
}
