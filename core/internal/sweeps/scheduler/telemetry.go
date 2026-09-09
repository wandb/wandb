package scheduler

// Telemetry events for the three tiers of failure the loop reaches for:
// exit, abandon the step, or give up on one run.
const (
	eventFatalError    = "sweep_scheduler_fatal_error"
	eventStepAbandoned = "sweep_scheduler_step_abandoned"
	eventRunDiscarded  = "sweep_scheduler_run_discarded"
)

// loopPhase names what the loop was doing when it gave up.
type loopPhase string

const (
	phaseWarmStart loopPhase = "warm_start"
	phasePoll      loopPhase = "poll"
	phaseEnqueue   loopPhase = "enqueue"
	phaseOptimizer loopPhase = "optimizer"
)

// Causes name why a suggestion was discarded instead of scheduled.
const (
	discardCauseBadConfig     = "bad_config"
	discardCauseEnqueueFailed = "enqueue_failed"
)

// recordFatalError counts a failure that forces the loop to exit.
//
// The detail is keyed "error", not "message": a log record's body is
// already its message, and a second one is ambiguous to query.
func (s *Scheduler) recordFatalError(phase loopPhase, detail string) {
	s.logger.RecordTelemetry(eventFatalError, map[string]string{
		"phase": string(phase),
		"error": detail,
	})
}

// recordStepAbandoned counts a step dropped whole to be retried.
func (s *Scheduler) recordStepAbandoned(phase loopPhase, err error) {
	s.logger.RecordTelemetry(eventStepAbandoned, map[string]string{
		"phase": string(phase),
		"error": err.Error(),
	})
}

// recordRunDiscarded counts a suggestion given up on by a loop that
// keeps scheduling.
func (s *Scheduler) recordRunDiscarded(cause, id string) {
	s.logger.RecordTelemetry(eventRunDiscarded, map[string]string{
		"cause": cause,
		"id":    id,
	})
}
