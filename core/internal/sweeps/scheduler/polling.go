package scheduler

import (
	"context"
	"errors"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// warmStartStep delivers one page of the sweep's pre-existing runs.
func (s *Scheduler) warmStartStep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	page, err := s.api.WarmStartPage(
		ctx, warmStartPageSize, s.warmCursor, s.metricKeys)
	if err != nil {
		if !retryable(ctx, err) {
			return s.doneFromError(ctx, phaseWarmStart, err)
		}

		// Keep the cursor and retry this page rather than skipping the
		// rest of the warm start.
		s.recordStepAbandoned(phaseWarmStart, err)
		s.logger.Warn(
			"scheduler: warm-start page rate limited; retrying it",
			"error", err)
		if done := s.sleep(ctx); done != nil {
			return done
		}
		return emptyWarmStartTask()
	}

	if sweepIsDone(page.SweepState) {
		return s.doneForSweepState(page.SweepState)
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
			len(s.metricKeys) > 0 &&
			!summaryHasAllMetrics(row.SummaryJSON, s.metricKeys) {
			// As in the poll path: a prior run without the objective
			// is a failure, not a sample.
			state = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
		}
		s.noteFinished(s.runsByName[row.Name], state)

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

// emptyWarmStartTask reports no prior runs, keeping the client in the
// warm-start phase while a page is retried.
func emptyWarmStartTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_WarmStart{
			WarmStart: &spb.SweepSchedulerServerWarmStartTask{HasMore: true},
		},
	}
}

// endReason is why the scheduler should stop.
//
// It is kept apart from the Done task itself so a caller can finish its
// bookkeeping first: doneTask drains the pending discards, so anything
// appended after it is built is never reported.
type endReason struct {
	reason  spb.SweepSchedulerServerDoneTask_Reason
	message string
}

// doneFromError maps a failed poll or enqueue onto a Done task, or
// returns nil if the loop should keep going.
func (s *Scheduler) doneFromError(
	ctx context.Context,
	phase loopPhase,
	err error,
) *spb.SweepSchedulerServerNextTaskResponse {
	end := s.endFromError(ctx, phase, err)
	if end == nil {
		return nil
	}
	return s.doneTask(end.reason, end.message)
}

// endFromError maps a failed call onto the reason the loop should end
// with, or nil if it should keep going.
//
// phase names the call for the fatal-error metric.
func (s *Scheduler) endFromError(
	ctx context.Context,
	phase loopPhase,
	err error,
) *endReason {
	if isShutdown(ctx, err) {
		return &endReason{
			reason: spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN,
		}
	}

	switch Classify(err) {
	case DispositionNotFound:
		return &endReason{
			reason:  spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
			message: "the sweep was deleted",
		}
	case DispositionRateLimited:
		s.logger.Warn("scheduler: rate limited by the backend", "error", err)
		return nil
	default:
		s.recordFatalError(phase, err.Error())
		return &endReason{
			reason:  spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
			message: err.Error(),
		}
	}
}

// isShutdown reports whether a failed call is the scheduler shutting
// down rather than the backend failing.
func isShutdown(ctx context.Context, err error) bool {
	return errors.Is(ctx.Err(), context.Canceled) ||
		errors.Is(err, context.Canceled)
}

// retryable reports whether an error is retryable (not fatal).
func retryable(ctx context.Context, err error) bool {
	return !isShutdown(ctx, err) &&
		Classify(err) == DispositionRateLimited
}

// doneForSweepState ends the scheduler for a state it cannot schedule
// under, reporting whether the sweep completed, the user stopped it or
// it failed.
func (s *Scheduler) doneForSweepState(
	state string,
) *spb.SweepSchedulerServerNextTaskResponse {
	var reason spb.SweepSchedulerServerDoneTask_Reason
	switch state {
	case sweepStateFinished:
		reason = spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED
	case sweepStateError, sweepStateFlapping, sweepStateCrashed:
		reason = spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR
	default:
		reason = spb.SweepSchedulerServerDoneTask_REASON_TERMINATED
	}
	return s.doneTask(reason, "the sweep is "+state)
}

// noteFinished counts a run toward finishedRunCount the first time it
// is observed to have completed successfully; a run counts once even
// if it is later adopted and polled again.
func (s *Scheduler) noteFinished(run *trackedRun, state spb.SweepRunState) {
	if run == nil || run.finishedCounted ||
		state != spb.SweepRunState_SWEEP_RUN_STATE_FINISHED {
		return
	}
	run.finishedCounted = true
	s.finishedRunCount++
}

// The sweep states the backend defines. upsertSweep stores whatever
// state a client sends without validating it, so others are possible.
const (
	// sweepStateFinished lets running runs finish; no new ones start.
	sweepStateFinished = "FINISHED"

	// sweepStateCanceled kills the running runs. The UI calls it
	// "Stopped"; it is what a user's stop or cancel produces.
	sweepStateCanceled = "CANCELED"

	// sweepStateError is the backend's catch-all failure.
	sweepStateError = "ERROR"

	// sweepStateFlapping is the backend pausing a sweep whose runs keep
	// crashing. The UI calls it "Crashed".
	sweepStateFlapping = "FLAPPING"

	// sweepStateCrashed is not a backend state: the launch scheduler
	// sets it on itself dying, and the backend stores it as-is.
	sweepStateCrashed = "CRASHED"
)

// sweepIsDone reports whether the sweep reached a state the scheduler
// can no longer schedule under. A state this build does not know is
// not one of them: the loop keeps going.
func sweepIsDone(state string) bool {
	switch state {
	case sweepStateFinished,
		sweepStateCanceled,
		sweepStateError,
		sweepStateFlapping,
		sweepStateCrashed:
		return true
	default:
		return false
	}
}

// runStates maps the backend's run state strings onto the protocol
// enum. An unlisted string maps to UNKNOWN; see stateOrFailed.
var runStates = map[string]spb.SweepRunState{
	"running":    spb.SweepRunState_SWEEP_RUN_STATE_RUNNING,
	"pending":    spb.SweepRunState_SWEEP_RUN_STATE_PENDING,
	"preempting": spb.SweepRunState_SWEEP_RUN_STATE_PREEMPTING,
	"preempted":  spb.SweepRunState_SWEEP_RUN_STATE_PREEMPTED,
	"finished":   spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
	"failed":     spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
	"crashed":    spb.SweepRunState_SWEEP_RUN_STATE_CRASHED,
	"killed":     spb.SweepRunState_SWEEP_RUN_STATE_KILLED,
}

// runStateOf classifies a backend run state string.
func runStateOf(state string) spb.SweepRunState {
	if mapped, ok := runStates[state]; ok {
		return mapped
	}
	return spb.SweepRunState_SWEEP_RUN_STATE_UNKNOWN
}

// stateOrFailed classifies a backend run state, reporting one this
// build does not recognize as FAILED.
func (s *Scheduler) stateOrFailed(stateString string) spb.SweepRunState {
	state := runStateOf(stateString)
	if state != spb.SweepRunState_SWEEP_RUN_STATE_UNKNOWN {
		return state
	}

	if !s.warnedUnrecognized[stateString] {
		s.warnedUnrecognized[stateString] = true
		s.logger.Error(
			"scheduler: unrecognized run state; reporting the run "+
				"as failed",
			"state", stateString)
	}
	return spb.SweepRunState_SWEEP_RUN_STATE_FAILED
}

// runStateIsTerminal reports whether the run has stopped for good.
// UNKNOWN, the placeholder for adopted runs, is not terminal.
//
// This must stay the exact complement of RunState.is_alive on the
// client: that is the predicate both optimizers branch on to decide
// whether a tell finalizes the trial, and a run finalized there can
// never be told again.
func runStateIsTerminal(state spb.SweepRunState) bool {
	switch state {
	case spb.SweepRunState_SWEEP_RUN_STATE_FINISHED,
		spb.SweepRunState_SWEEP_RUN_STATE_FAILED,
		spb.SweepRunState_SWEEP_RUN_STATE_CRASHED,
		spb.SweepRunState_SWEEP_RUN_STATE_KILLED,
		spb.SweepRunState_SWEEP_RUN_STATE_PREEMPTED:
		return true
	default:
		return false
	}
}
