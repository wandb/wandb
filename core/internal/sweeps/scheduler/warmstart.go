package scheduler

import (
	"context"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// warmStartStep delivers one page of the sweep's pre-existing runs.
//
// Pages are delivered back to back; the client's adoptions come back in
// each page's result and are merged by applyResult. A failed page skips
// the rest of the warm start rather than failing the sweep: the search
// just starts with less history.
func (s *Scheduler) warmStartStep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	page, err := s.api.PollPage(ctx, warmStartPageSize, s.warmCursor, s.metricKey)
	if err != nil {
		if done := s.doneFromError(ctx, err); done != nil {
			return done
		}
		s.logger.Warn(
			"scheduler: warm-start page failed; starting without the " +
				"remaining prior runs")
		s.warmDone = true
		return s.generationTask(nil, nil, 0)
	}

	if !sweepIsActive(page.SweepState) {
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
			"the sweep is "+page.SweepState)
	}

	task := &spb.SweepSchedulerServerWarmStartTask{
		HasMore: page.NextCursor != nil,
	}
	for _, row := range page.Runs {
		if s.runsByName[row.Name] == nil {
			s.runsByName[row.Name] = &trackedRun{
				state: TrackingRetired,
				name:  row.Name,
			}
		}

		state := s.stateOrFailed(row.State)
		if state == spb.SweepRunState_SWEEP_RUN_STATE_FINISHED &&
			s.metricKey != "" &&
			!summaryHasMetric(row.SummaryJSON, s.metricKey) {
			// The same reclassification the poll path applies: a prior
			// run without the objective is a failure, not a sample.
			state = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
		}

		data := &spb.SweepSchedulerServerRunData{
			WandbRunId: row.Name,
			State:      state,
			ConfigJson: flattenWireConfig(row.ConfigJSON),
		}
		if runStateIsTerminal(state) {
			data.SummaryJson = row.SummaryJSON
			data.HistoryJson = row.HistoryJSON
			task.FinishedRuns = append(task.FinishedRuns, data)
		} else {
			task.ActiveRuns = append(task.ActiveRuns, data)
		}
	}

	s.warmCursor = page.NextCursor
	if page.NextCursor == nil {
		s.warmDone = true
	}

	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_WarmStart{
			WarmStart: task,
		},
	}
}
