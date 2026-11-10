package monitor

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestWriterInfo_RanksAndSchedulerJob(t *testing.T) {
	t.Setenv("RANK", "0")
	t.Setenv("WORLD_SIZE", "16")
	t.Setenv("SLURM_JOB_ID", "48213")
	t.Setenv("SLURM_STEP_ID", "0")
	t.Setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")

	// No process has this PID, so the lookup falls back to this process.
	writer := writerInfo("writer-id", "", -1)

	assert.NotNil(t, writer.Rank)
	assert.Zero(t, writer.GetRank())
	assert.Nil(t, writer.LocalRank)
	assert.EqualValues(t, 16, writer.GetWorldSize())
	assert.Equal(t, "slurm:48213.0", writer.GetSchedulerJob())

	// The namespace comes from the pod's service account, if this is one.
	env := func(name string) (string, bool) {
		return "", name == "KUBERNETES_SERVICE_HOST"
	}
	job := schedulerJob(env, "pod-0")
	assert.True(t, strings.HasPrefix(job, "k8s:") && strings.HasSuffix(job, "/pod-0"), job)
}
