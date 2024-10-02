package monitor_test

import (
	"reflect"
	"testing"

	"github.com/wandb/wandb/core/pkg/monitor"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSLURMProbe(t *testing.T) {
	tests := []struct {
		name     string
		envVars  map[string]string
		expected *spb.MetadataRequest
	}{
		{
			name: "With SLURM environment variables",
			envVars: map[string]string{
				"SLURM_JOB_ID":   "12345",
				"SLURM_JOB_NAME": "test_job",
			},
			expected: &spb.MetadataRequest{
				Slurm: map[string]string{
					"job_id":   "12345",
					"job_name": "test_job",
				},
			},
		},
		{
			name:     "Without SLURM environment variables",
			envVars:  map[string]string{},
			expected: nil,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Set up the test environment
			for k, v := range tt.envVars {
				t.Setenv(k, v)
			}

			slurm := monitor.NewSLURM()
			result := slurm.Probe()

			if !reflect.DeepEqual(result, tt.expected) {
				t.Errorf("Probe() = %v, want %v", result, tt.expected)
			}
		})
	}
}
