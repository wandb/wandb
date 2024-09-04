package filestream

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

// PreemptingUpdate indicates a run's preemption status.
//
// "Preemptible runs and sweeps" were added in
// https://github.com/wandb/wandb/pull/2142
//
// This is a mechanism to tell the backend that the run will be unable to
// even send heartbeats for some time, and to be more lenient with
// deciding if the run crashed.
type PreemptingUpdate struct {
	Record *spb.RunPreemptingRecord
}

func (u *PreemptingUpdate) Apply(ctx UpdateContext) error {
	ctx.MakeRequest(&FileStreamRequest{
		Preempting: true,
	})

	return nil
}
