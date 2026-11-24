package monitor

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/wandb/wandb/core/internal/sharedmode"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writerInfo describes the process with the given PID as a writer of the
// run, from the environment its launcher and scheduler gave it.
func writerInfo(id sharedmode.ClientID, label string, pid int32) *spb.WriterInfo {
	env := launcherEnv(pid)
	writer := &spb.WriterInfo{
		Id:        string(id),
		Label:     label,
		Rank:      envInt(env, "RANK"),
		LocalRank: envInt(env, "LOCAL_RANK"),
		NodeRank:  envInt(env, "GROUP_RANK", "NODE_RANK"),
		WorldSize: envInt(env, "WORLD_SIZE"),
	}
	writer.Hostname, _ = os.Hostname()
	writer.SchedulerJob = schedulerJob(env, writer.Hostname)
	return writer
}

// launcherEnv looks up variables in the environment the process with the
// given PID started with.
//
// One wandb-core can serve several processes, each with its own rank, so its
// own environment is only the fallback where another's cannot be read.
func launcherEnv(pid int32) func(string) (string, bool) {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/environ", pid))
	if err != nil {
		return os.LookupEnv
	}
	env := make(map[string]string)
	for entry := range strings.SplitSeq(string(data), "\x00") {
		if name, value, ok := strings.Cut(entry, "="); ok {
			env[name] = value
		}
	}
	return func(name string) (string, bool) {
		value, ok := env[name]
		return value, ok
	}
}

// schedulerJob names the scheduler's job: the Slurm job and step, or the
// Kubernetes pod, whose name is its hostname.
func schedulerJob(env func(string) (string, bool), hostname string) string {
	if job, _ := env("SLURM_JOB_ID"); job != "" {
		if step, _ := env("SLURM_STEP_ID"); step != "" {
			return "slurm:" + job + "." + step
		}
		return "slurm:" + job
	}
	if _, ok := env("KUBERNETES_SERVICE_HOST"); ok {
		namespace, _ := os.ReadFile(
			"/var/run/secrets/kubernetes.io/serviceaccount/namespace")
		return "k8s:" + strings.TrimSpace(string(namespace)) + "/" + hostname
	}
	return ""
}

// envInt returns the integer value of the first of the variables that is
// set, or nil.
func envInt(env func(string) (string, bool), names ...string) *int32 {
	for _, name := range names {
		value, ok := env(name)
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
