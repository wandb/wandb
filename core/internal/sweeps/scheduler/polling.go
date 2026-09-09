package scheduler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"hash/fnv"
	"maps"
	"slices"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// warmStartStep delivers one page of the sweep's pre-existing runs.
func (s *Scheduler) warmStartStep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	page, err := s.api.PollPage(ctx, warmStartPageSize, s.warmCursor, s.metricKey)
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
			s.metricKey != "" &&
			!summaryHasMetric(row.SummaryJSON, s.metricKey) {
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
// with, or nil if it should keep going. The API layer already recorded
// the failure in the backoff.
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
		// The backoff has already widened the next wait.
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

// finishExhausted ends the sweep because the search space ran out.
func (s *Scheduler) finishExhausted(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.finishSweep(ctx)
	return s.doneTask(
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		"the search space is exhausted")
}

// finishRunCap ends the sweep because the run cap was hit
func (s *Scheduler) finishRunCap(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.finishSweep(ctx)
	return s.doneTask(
		spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
		"the run cap was hit")
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

// finishSweep marks the sweep FINISHED, best-effort: a failed upsert
// only costs the state label.
func (s *Scheduler) finishSweep(ctx context.Context) {
	err := s.api.UpsertSweepState(ctx, s.sweepNodeID, sweepStateFinished)
	if err != nil {
		s.logger.Warn(
			"scheduler: failed to mark the sweep finished", "error", err)
	}
}

// pollSnapshot is one complete walk of the sweep's runs.
type pollSnapshot struct {
	sweepState string

	// rows is keyed by run name; order preserves the backend's ordering
	// for deterministic task assembly.
	rows  map[string]PollRun
	order []string
}

// pollAll walks every page of the sweep's runs.
func (s *Scheduler) pollAll(ctx context.Context) (*pollSnapshot, error) {
	snapshot := &pollSnapshot{rows: make(map[string]PollRun)}

	var cursor *string
	for {
		page, err := s.api.PollPage(ctx, runsPageSize, cursor, s.metricKey)
		if err != nil {
			return nil, err
		}

		snapshot.sweepState = page.SweepState
		for _, run := range page.Runs {
			if _, ok := snapshot.rows[run.Name]; !ok {
				snapshot.order = append(snapshot.order, run.Name)
			}
			snapshot.rows[run.Name] = run
		}

		if page.NextCursor == nil {
			return snapshot, nil
		}
		cursor = page.NextCursor
	}
}

// generationStep polls the sweep and assembles the next generation task.
func (s *Scheduler) generationStep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	snapshot, err := s.pollAll(ctx)
	if err != nil {
		if done := s.doneFromError(ctx, phasePoll, err); done != nil {
			return done
		}
		// Rate limited: deliver an empty task and try again next poll.
		s.recordStepAbandoned(phasePoll, err)
		return s.generationTask(nil, nil, 0)
	}
	s.noteBackendState(snapshot)

	if sweepIsDone(snapshot.sweepState) {
		return s.doneForSweepState(snapshot.sweepState)
	}
	if snapshot.sweepState == sweepStatePaused {
		return s.generationTask(nil, nil, 0)
	}

	if s.runCap > 0 && s.finishedRunCount >= s.runCap {
		return s.finishRunCap(ctx)
	}

	s.observeUntrackedRuns(snapshot)

	updates, candidates := s.buildUpdates(ctx, snapshot)

	if s.exhausted {
		// Every scheduled run has reported, so the sweep is done.
		if s.trackedRunCount() == 0 {
			return s.finishExhausted(ctx)
		}
		return s.generationTask(updates, candidates, 0)
	}
	return s.generationTask(updates, candidates, s.askBudget())
}

// noteBackendState logs, every stagnantLogInterval, that the sweep's
// state and every row's name, state and summary are as the previous
// poll saw them, giving a stuck sweep a heartbeat to debug from.
func (s *Scheduler) noteBackendState(snapshot *pollSnapshot) {
	fingerprint := snapshotFingerprint(snapshot)
	now := s.clock.Now()

	if fingerprint != s.lastFingerprint {
		s.lastFingerprint = fingerprint
		s.lastChange = now
		s.lastStagnantLog = now
		return
	}

	if now.Sub(s.lastStagnantLog) < stagnantLogInterval {
		return
	}
	s.lastStagnantLog = now
	s.logger.Info(
		"scheduler: no change in the sweep detected by polling",
		"since", now.Sub(s.lastChange).Round(time.Second).String(),
		"runs", len(snapshot.order))
}

// snapshotFingerprint condenses a poll's observable state. Rows are
// hashed in name order so backend ordering cannot look like change.
func snapshotFingerprint(snapshot *pollSnapshot) string {
	names := slices.Sorted(maps.Keys(snapshot.rows))

	digest := fnv.New64a()
	writeField := func(field string) {
		_, _ = digest.Write([]byte(field))
		_, _ = digest.Write([]byte{0})
	}
	writeField(snapshot.sweepState)
	for _, name := range names {
		row := snapshot.rows[name]
		writeField(name)
		writeField(row.State)
		writeField(row.SummaryJSON)
	}
	return string(digest.Sum(nil))
}

// observeUntrackedRuns flags rows the scheduler is not tracking.
//
// Untracked runs never count toward the batch: batch_size budgets
// only this scheduler's own runs. A reported run that is alive again
// was resumed, and cannot be re-told: strategies are append-only.
func (s *Scheduler) observeUntrackedRuns(snapshot *pollSnapshot) {
	for _, name := range snapshot.order {
		row := snapshot.rows[name]
		alive := !runStateIsTerminal(runStateOf(row.State))

		if run := s.runsByName[name]; run != nil {
			if run.state == TrackingRetired && run.reported && alive {
				s.warnOnce(&s.warnedResumed,
					"scheduler: run "+name+" resumed after its result "+
						"was reported; the optimizer will not receive "+
						"further updates for it")
			}
			continue
		}

		s.runsByName[name] = &trackedRun{
			state: TrackingRetired,
			name:  name,
		}
		if alive && s.warmDone {
			s.warnOnce(&s.warnedForeign,
				"scheduler: untracked runs are appearing in the sweep; "+
					"another scheduler may be driving it")
		}
	}
}

func (s *Scheduler) warnOnce(flag *bool, message string) {
	if *flag {
		return
	}
	*flag = true
	s.logger.Warn(message)
}

// buildUpdates turns the poll snapshot into run updates for the
// optimizer and the list of prune candidates.
func (s *Scheduler) buildUpdates(
	ctx context.Context,
	snapshot *pollSnapshot,
) ([]*spb.SweepSchedulerServerRunUpdate, []string) {
	var updates []*spb.SweepSchedulerServerRunUpdate
	var candidates []string

	for _, run := range s.trackedInOrder(snapshot) {
		row, present := snapshot.rows[run.name]
		switch {
		case present && row.State != "":
			s.updateTrackedRunFromPoll(run, row)

		case present:
			// The row exists but its state came back empty.
			// The backend and this SDK have mismatched GQL schemas
			// Report this for tracking
			run.storageID = row.StorageID
			s.logger.CaptureError(
				"scheduler",
				fmt.Errorf(
					"scheduler: run %q returned no readable state; "+
						"likely a backend/SDK GQL schema mismatch",
					run.name),
				"run", run.name)

		default:
			if !s.reapIfGone(ctx, run) {
				// Missing, but confirmed to still exist: no update
				// this poll.
				continue
			}
		}

		terminal := runStateIsTerminal(run.runState)
		updates = append(updates, &spb.SweepSchedulerServerRunUpdate{
			Run: &spb.SweepSchedulerServerRunData{
				WandbRunId:     run.name,
				OptimizerRunId: run.optimizerRunID,
				State:          run.runState,
				ConfigJson:     flattenWireConfig(row.ConfigJSON),
				SummaryJson:    row.SummaryJSON,
				HistoryJson:    row.HistoryJSON,
			},
		})

		if terminal {
			run.state = TrackingTerminalDelivered
		} else if run.runState == spb.SweepRunState_SWEEP_RUN_STATE_RUNNING ||
			run.runState == spb.SweepRunState_SWEEP_RUN_STATE_PENDING {
			candidates = append(candidates, run.optimizerRunID)
		}
	}
	return updates, candidates
}

// trackedInOrder returns the tracked runs, poll order first and then
// runs absent from the poll, so update order is deterministic.
func (s *Scheduler) trackedInOrder(snapshot *pollSnapshot) []*trackedRun {
	var runs []*trackedRun
	for _, name := range snapshot.order {
		if run := s.runsByName[name]; run != nil && run.isTracked() {
			runs = append(runs, run)
		}
	}
	for _, run := range s.runs {
		if !run.isTracked() {
			continue
		}
		if _, ok := snapshot.rows[run.name]; !ok {
			runs = append(runs, run)
		}
	}
	return runs
}

// updateTrackedRunFromPoll applies one readable poll row to a tracked
// run, including the state reclassifications.
func (s *Scheduler) updateTrackedRunFromPoll(run *trackedRun, row PollRun) {
	run.storageID = row.StorageID

	state := s.stateOrFailed(row.State)

	if state == spb.SweepRunState_SWEEP_RUN_STATE_FINISHED &&
		s.metricKey != "" && !summaryHasMetric(row.SummaryJSON, s.metricKey) {
		// Report it failed so strategies do not treat a missing
		// objective as a great one.
		s.logger.Warn(
			"scheduler: run finished without the sweep metric; "+
				"reporting it as failed",
			"run", run.name, "metric", s.metricKey)
		state = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
	}
	run.runState = state
	s.noteFinished(run, state)
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

// reapIfGone confirms with a direct read whether a run absent from a
// complete poll still exists, and reports whether it was confirmed
// gone and failed.
func (s *Scheduler) reapIfGone(
	ctx context.Context,
	run *trackedRun,
) bool {
	exists, err := s.api.ConfirmRunExists(ctx, run.name)
	if err != nil {
		s.logger.Warn(
			"scheduler: could not confirm a missing run's deletion",
			"run", run.name, "error", err)
		return false
	}
	if exists {
		// A pagination hiccup, not a deletion.
		return false
	}

	s.logger.Warn(
		"scheduler: run was deleted; reporting it as failed",
		"run", run.name)
	run.runState = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
	return true
}

// askBudget is how many new suggestions the next ask may return.
func (s *Scheduler) askBudget() int {
	occupied := 0
	for _, run := range s.runs {
		if run.isTracked() && runStateOccupiesSlot(run.runState) {
			occupied++
		}
	}
	return s.batchSize - occupied
}

// enqueueSuggestions schedules the optimizer's new runs. A non-nil
// return ends the scheduler with that Done task.
//
// Every suggestion not durably enqueued is discarded so the optimizer
// releases it instead of counting a run that will never happen.
//
// A pending Stop does not skip this: shutdown still enqueues the batch
// the client just produced, and Step returns Done on its next wait.
func (s *Scheduler) enqueueSuggestions(
	ctx context.Context,
	suggestions []*spb.SweepSchedulerClientRunSuggestion,
) *spb.SweepSchedulerServerNextTaskResponse {
	if len(suggestions) == 0 {
		return nil
	}

	// The sweep may have finished while the optimizer was thinking.
	facts, err := s.api.FetchSweep(ctx)
	switch {
	case err != nil && Classify(err) == DispositionNotFound:
		s.discardAll(suggestions)
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
			"the sweep was deleted")
	case err != nil:
		// Let the enqueues themselves surface a persistent problem.
		s.logger.Error(
			"scheduler: could not re-check the sweep before "+
				"enqueueing", "error", err)
	case sweepIsDone(facts.State):
		s.discardAll(suggestions)
		return s.doneForSweepState(facts.State)
	case facts.State == sweepStatePaused:
		// Pausing is not terminal, but new runs must not start; the
		// optimizer gets these back as discards.
		s.discardAll(suggestions)
		return nil
	}

	for i, suggestion := range suggestions {
		end := s.enqueueOne(ctx, suggestion)
		if end == nil {
			continue
		}
		// Discard the suggestions this scheduler will never reach before
		// building the Done, which drains the discard list. enqueueOne
		// has already discarded the one it failed on.
		s.discardAll(suggestions[i+1:])
		return s.doneTask(end.reason, end.message)
	}
	return nil
}

// enqueueOne schedules a single suggestion, discarding it if that
// fails. A non-nil return ends the scheduler for that reason.
func (s *Scheduler) enqueueOne(
	ctx context.Context,
	suggestion *spb.SweepSchedulerClientRunSuggestion,
) *endReason {
	id := suggestion.OptimizerRunId
	if id == "" {
		// Ids key run tracking, so this one cannot be tracked. It is not
		// reported as a discard: an empty id names no run to forget.
		s.logger.Warn("scheduler: dropping suggestion with an empty id")
		return nil
	}
	if s.runs[id] != nil {
		// Not reported as a discard either. The id belongs to a run this
		// scheduler already tracks, and the client forgets discarded ids
		// before applying the task's updates, so reporting it would
		// retire that run instead of this bogus suggestion.
		s.logger.Warn(
			"scheduler: dropping suggestion with a duplicate "+
				"optimizer run id", "id", id)
		return nil
	}

	// Retired until the enqueue proves otherwise; the record also
	// reserves the id for the scheduler's lifetime.
	run := &trackedRun{state: TrackingRetired, optimizerRunID: id}
	s.runs[id] = run

	wireConfig, err := wrapFlatConfig(suggestion.ConfigJson)
	if err != nil {
		s.logger.Warn(
			"scheduler: dropping suggestion with an unusable config",
			"id", id, "error", err)
		s.discards = append(s.discards, id)
		s.recordRunDiscarded(discardCauseBadConfig, id)
		return nil
	}

	mintedID, err := s.api.EnqueueRun(ctx, s.sweepNodeID, wireConfig)
	if err != nil {
		// The discard rides the next task, Done or not, so the optimizer
		// forgets a suggestion that will never run.
		s.discards = append(s.discards, id)
		s.logger.Error(
			"scheduler: failed to enqueue a suggestion",
			"id", id, "error", err)
		// A rate limit costs only this suggestion; anything else has
		// already outlived the client's retries and ends the scheduler.
		end := s.endFromError(ctx, phaseEnqueue, err)
		if end == nil {
			s.recordRunDiscarded(discardCauseEnqueueFailed, id)
		}
		return end
	}

	s.logger.Info("scheduler: enqueued run", "id", id)
	// The minted run is guaranteed to appear in the sweep as pending;
	// one that never does was deleted and is reaped like any other
	// missing tracked run.
	run.state = TrackingInFlight
	run.name = mintedID
	run.runState = spb.SweepRunState_SWEEP_RUN_STATE_PENDING
	s.runsByName[mintedID] = run
	return nil
}

// discardAll routes suggestions to the discard channel.
func (s *Scheduler) discardAll(
	suggestions []*spb.SweepSchedulerClientRunSuggestion,
) {
	for _, suggestion := range suggestions {
		s.discards = append(s.discards, suggestion.OptimizerRunId)
	}
}

// wrapFlatConfig converts the protocol's flat {param: v} config form
// into the backend's {param: {"value": v}} wire form.
func wrapFlatConfig(flatJSON string) (string, error) {
	var flat map[string]any
	if err := json.Unmarshal([]byte(flatJSON), &flat); err != nil {
		return "", fmt.Errorf("scheduler: parsing suggestion config: %v", err)
	}

	wire := make(map[string]any, len(flat))
	for name, value := range flat {
		wire[name] = map[string]any{"value": value}
	}

	encoded, err := json.Marshal(wire)
	if err != nil {
		return "", fmt.Errorf("scheduler: encoding wire config: %v", err)
	}
	return string(encoded), nil
}

// applyPrunes stops the runs the optimizer pruned.
//
// Ids outside the candidates offered with the task are ignored. Once
// the backend accepts the stop, the run is retired immediately
// failure to stop a run can be retried again by the optimizer
func (s *Scheduler) applyPrunes(ctx context.Context, pruneIDs []string) {
	if len(pruneIDs) == 0 {
		return
	}

	for _, id := range pruneIDs {
		if !s.lastPruneCandidates[id] {
			continue
		}
		run := s.runs[id]
		if run == nil || !run.isTracked() || runStateIsTerminal(run.runState) {
			continue
		}

		stopped, err := s.api.StopRun(ctx, run.storageID)
		if err != nil {
			// Leave the run a candidate; the optimizer may prune it
			// again and must tolerate the repeat.
			s.logger.Error(
				"scheduler: failed to stop a pruned run",
				"run", run.name, "error", err)
			continue
		}
		if !stopped {
			s.logger.Warn(
				"scheduler: the backend refused to stop a pruned run; "+
					"it may have already stopped",
				"run", run.name)
		}

		s.logger.Info(
			"scheduler: stopped pruned run; retiring it", "run", run.name)
		run.state = TrackingRetired
	}
}

// The sweep states the backend defines. upsertSweep stores whatever
// state a client sends without validating it, so others are possible.
const (
	// sweepStatePending accepts configuration changes.
	sweepStatePending = "PENDING"

	// sweepStateRunning hands agents new runs.
	sweepStateRunning = "RUNNING"

	// sweepStatePaused keeps running runs alive but starts no new ones.
	sweepStatePaused = "PAUSED"

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

// runStateOccupiesSlot reports whether the run counts toward the
// scheduler's batch of in-flight runs.
func runStateOccupiesSlot(state spb.SweepRunState) bool {
	return !runStateIsTerminal(state)
}
