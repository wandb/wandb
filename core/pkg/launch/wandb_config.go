package launch

import (
	"github.com/wandb/wandb/core/internal/data_types"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Selector for job inputs from the wandb.config.
//
// The includePaths and excludePaths are used to filter down the run config
// before it is converted to a schema and saved as job inputs.
type launchWandbConfigParameters struct {
	includePaths []ConfigPath
	excludePaths []ConfigPath
	inputSchema  *string
}

func newWandbConfigParameters() *launchWandbConfigParameters {
	return &launchWandbConfigParameters{[]ConfigPath{}, []ConfigPath{}, nil}
}

func (p *launchWandbConfigParameters) appendIncludePaths(
	includePaths []*spb.JobInputPath,
) {
	for _, path := range includePaths {
		p.includePaths = append(p.includePaths, path.Path)
	}
}

func (p *launchWandbConfigParameters) appendExcludePaths(
	excludePaths []*spb.JobInputPath,
) {
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
//
// If there are any errors in the process, the function logs them and returns
// an unknown type representation. The errors should never happen in practice.
func (j *JobBuilder) inferRunConfigTypes() (*data_types.TypeRepresentation, error) {
	config := NewConfigFrom(j.runConfig.CloneTree())
	typeInfo := data_types.ResolveTypes(
		config.filterTree(
			j.wandbConfigParameters.include(),
			j.wandbConfigParameters.exclude(),
		),
	)
	return &typeInfo, nil
}
