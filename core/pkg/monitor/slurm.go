package monitor

import (
	"os"
	"strings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SLURM is used to capture SLURM-related environment variables
type SLURM struct {
	name string
}

func getSlurmEnvVars() map[string]string {
	// capture SLURM-related environment variables
	slurmVars := make(map[string]string)
	for _, envVar := range os.Environ() {
		keyValPair := strings.SplitN(envVar, "=", 2)
		key := keyValPair[0]
		value := keyValPair[1]

		if strings.HasPrefix(key, "SLURM_") {
			suffix := strings.ToLower(strings.TrimPrefix(key, "SLURM_"))
			slurmVars[suffix] = value
		}
	}
	return slurmVars
}

func NewSLURM() *SLURM {
	return &SLURM{name: "slurm"}
}

func (g *SLURM) Name() string { return g.name }

func (g *SLURM) Sample() (map[string]any, error) { return nil, nil }

func (g *SLURM) IsAvailable() bool { return false }

func (g *SLURM) Probe() *spb.MetadataRequest {
	slurmVars := getSlurmEnvVars()
	if len(slurmVars) == 0 {
		return nil
	}

	systemInfo := &spb.MetadataRequest{}
	for k, v := range getSlurmEnvVars() {
		if systemInfo.Slurm == nil {
			systemInfo.Slurm = make(map[string]string)
		}
		systemInfo.Slurm[k] = v
	}

	return systemInfo
}
