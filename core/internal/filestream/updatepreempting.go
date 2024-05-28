package filestream

import "github.com/wandb/wandb/core/pkg/service"

// PreemptingUpdate indicates a run's preemption status.
//
// "Preemptible runs and sweeps" were added in
// https://github.com/wandb/wandb/pull/2142
//
// This is a mechanism to tell the backend that the run will be unable to
// even send heartbeats for some time, and to be more lenient with
// deciding if the run crashed.
type PreemptingUpdate struct {
	Record *service.RunPreemptingRecord
}

func (u *PreemptingUpdate) Apply(ctx UpdateContext) error {
	ctx.ModifyRequest(&collectorPreemptingUpdate{})

	return nil
}

type collectorPreemptingUpdate struct{}

func (u *collectorPreemptingUpdate) Apply(state *CollectorState) {
	state.Buffer.HasPreempting = true
	state.Buffer.Preempting = true
}
