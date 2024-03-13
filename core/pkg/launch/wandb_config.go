package launch

import (
	"github.com/wandb/wandb/core/internal/data_types"
	"github.com/wandb/wandb/core/pkg/service"
)

// Represents the wandb config filters received by the internal process.
type launchWandbConfigParameters struct {
	includePaths []ConfigPath
	excludePaths []ConfigPath
}

func newWandbConfigParameters() *launchWandbConfigParameters {
	return &launchWandbConfigParameters{[]ConfigPath{}, []ConfigPath{}}
}

func (p *launchWandbConfigParameters) appendIncludePaths(includePaths []*service.ConfigFilterPath) {
	for _, path := range includePaths {
		p.includePaths = append(p.includePaths, path.Path)
	}
}

func (p *launchWandbConfigParameters) appendExcludePaths(excludePaths []*service.ConfigFilterPath) {
	for _, path := range excludePaths {
		p.excludePaths = append(p.excludePaths, path.Path)
	}
}

func (p *launchWandbConfigParameters) include() []ConfigPath {
	return p.includePaths
}

func (p *launchWandbConfigParameters) exclude() []ConfigPath {
	return p.excludePaths
}

// Create a typed representation of the wandb config inputs.
//
// Loads config filters received by the internal process, uses them to filter
// down a copy of the run config, and then produces a TypedRepresentation for
// the filtered config.
func (j *JobBuilder) getWandbConfigInputs() data_types.TypeRepresentation {
	config := NewConfigFrom(j.runConfig.CloneTree())
	return data_types.ResolveTypes(
		config.FilterTree(
			j.wandbConfigParameters.include(),
			j.wandbConfigParameters.exclude(),
		))
}

// Saves the received LaunchWandbConfigParametersRecords for later use.
//
// Also sets a flag to save the shape of the run config to the metadata rather
// than `wandb-job.json`.
func (j *JobBuilder) HandleLaunchWandbConfigParametersRecord(wandbConfigParameters *service.LaunchWandbConfigParametersRecord) {
	j.saveShapeToMetadata = true
	j.wandbConfigParameters.appendIncludePaths(wandbConfigParameters.IncludePaths)
	j.wandbConfigParameters.appendExcludePaths(wandbConfigParameters.ExcludePaths)
}
