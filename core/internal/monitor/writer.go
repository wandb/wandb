package monitor

import (
	"os"
	"strconv"

	"github.com/wandb/wandb/core/internal/sharedmode"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writerInfo describes this process as a writer of the run, from the
// launcher's and the scheduler's environment variables.
func writerInfo(id sharedmode.ClientID, label string) *spb.WriterInfo {
	writer := &spb.WriterInfo{
		Id:        string(id),
		Label:     label,
		Rank:      envInt("RANK"),
		LocalRank: envInt("LOCAL_RANK"),
		NodeRank:  envInt("GROUP_RANK", "NODE_RANK"),
		WorldSize: envInt("WORLD_SIZE"),
	}
	writer.Hostname, _ = os.Hostname()

	if job := os.Getenv("SLURM_JOB_ID"); job != "" {
		writer.SchedulerJob = "slurm:" + job
		if step := os.Getenv("SLURM_STEP_ID"); step != "" {
			writer.SchedulerJob += "." + step
		}
	}
	return writer
}

// envInt returns the integer value of the first of the variables that is
// set, or nil.
func envInt(names ...string) *int32 {
	for _, name := range names {
		value, ok := os.LookupEnv(name)
		if !ok {
			continue
		}
		n, err := strconv.ParseInt(value, 10, 32)
		if err != nil {
			return nil
		}
		n32 := int32(n)
		return &n32
	}
	return nil
}
