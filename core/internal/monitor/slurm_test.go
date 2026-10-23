package monitor

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSlurmEnvVars(t *testing.T) {
	t.Setenv("SLURM_JOB_ID", "12345")
	t.Setenv("SLURM_JOB_NAME", "test_job")

	assert.Equal(t,
		map[string]string{"job_id": "12345", "job_name": "test_job"},
		slurmEnvVars(),
	)
}
