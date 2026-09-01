package scheduler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"hash/fnv"
	"maps"
	"net/url"
	"slices"
	"sync"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// defaultPollInterval is how long the loop waits between polls when
	// the client does not choose an interval.
	defaultPollInterval = 5 * time.Second

	// defaultBatchSize is the in-flight run target when the client does
	// not choose one.
	defaultBatchSize = 1

	// stagnantLogInterval is how often the loop logs that polling has
	// detected no change in the backend's state.
	stagnantLogInterval = time.Minute

	// stopGrace is how long a pruned run may keep running before its
	// StopRun is reissued; after a second grace period it stops counting
	// toward the batch so a stuck run cannot stall the sweep.
	stopGrace = 2 * time.Minute
)

// Scheduler drives one sweep; it implements TaskResolver.
//
// All state is confined to Step, which the task machine serializes, so
// no field except the stop channel needs synchronization. Every run the
// scheduler touches is one trackedRun record whose lifecycle state is a
// TrackingState; see that type for the states and their order.
type Scheduler struct {
	api    *trackedAPI
	logger *observability.CoreLogger

	sweepNodeID  string
	metricKey    string
	batchSize    int
	pollInterval time.Duration

	stopOnce sync.Once
	stop     chan struct{}

	// now and timer stub time for tests.
	now   func() time.Time
	timer func(d time.Duration) (<-chan time.Time, func())

	warmCursor *string
	warmDone   bool

	// runs holds one record per accepted suggestion or adopted run,
	// keyed by optimizer run id, in every lifecycle state. Records are
	// never removed, so an id stays reserved for the scheduler's
	// lifetime.
	runs map[string]*trackedRun

	// runsByName indexes the same records by W&B run name once it is
	// known. Runs this scheduler never scheduled or adopted have no
	// optimizer id and appear only here.
	runsByName map[string]*trackedRun

	// discards accumulates optimizer run ids of suggestions that were
	// accepted but never durably scheduled, reported on the next task.
	discards []string

	// lastPruneCandidates is the candidate set offered by the latest
	// generation task; prune ids outside it are ignored.
	lastPruneCandidates map[string]bool

	// exhausted means the optimizer has no more runs to propose, so the
	// loop stops asking and waits for the runs already scheduled.
	exhausted bool

	warnedUnrecognized map[string]bool
	warnedForeign      bool
	warnedResumed      bool

	// lastFingerprint, lastChange and lastStagnantLog drive the
	// stagnation heartbeat; see noteBackendState.
	lastFingerprint string
	lastChange      time.Time
	lastStagnantLog time.Time
}

var _ TaskResolver = (*Scheduler)(nil)
var _ TaskResolverFactory = NewTaskResolverFactory(nil)

// TrackingState is where a run stands in its lifecycle.
//
// A suggestion's states, in order: proposed (the Python client receives
// it from its optimizer and reports it with an generation result — the
// scheduler has no record yet), then TrackingInFlight,
// TrackingTerminalDelivered and TrackingRetired.
type TrackingState int

const (
	// TrackingInFlight: the run is tracked. An enqueued suggestion is
	// in flight the moment enqueueSweepRun returns its run id: the run
	// is guaranteed to appear in the sweep as pending, and one that
	// stays missing is handled like any tracked run deleted by the
	// user. Every generation task carries the run's latest state and
	// metrics.
	TrackingInFlight TrackingState = iota

	// TrackingTerminalDelivered: the run's final update rode the latest
	// task; the run retires only once that task's result is accepted,
	// so a lost response cannot lose the terminal tell.
	TrackingTerminalDelivered

	// TrackingRetired: the scheduler will ignore this run.
	TrackingRetired
)

// trackedRun is one run of the sweep as the scheduler knows it — born
// from a suggestion, adopted at warm start, or merely observed in a
// poll — together with the lifecycle state it is in.
type trackedRun struct {
	state TrackingState

	// optimizerRunID is the id the optimizer tracks the run by; empty
	// for runs this scheduler did not schedule or adopt.
	optimizerRunID string

	// name is the run's W&B name; for an enqueued suggestion, the id
	// enqueueSweepRun returned.
	name string

	// storageID is the run's GraphQL node id, captured from polls and
	// required to stop the run.
	storageID string

	// runState is the run's state as the backend reports it.
	runState spb.SweepRunState

	// reported means the run's terminal update was delivered and
	// acknowledged: a retired reported run seen alive again was
	// resumed rather than foreign or excluded.
	reported bool

	// pruned means the optimizer asked to stop this run. It receives one
	// final terminal update and is excluded from tells and prune
	// candidates until then.
	pruned bool

	// stopIssued and stopRetried track the StopRun calls made for a
	// pruned run, so a run whose client ignores the stop flag is asked
	// once more and then stops occupying a batch slot.
	stopIssued  time.Time
	stopRetried bool

	// unknownStreak counts consecutive polls whose row for this run was
	// unreadable; two in a row fail the run.
	unknownStreak int

	// missingStreak counts consecutive complete polls the run was absent
	// from; two in a row (plus a confirming query) reap it as deleted.
	missingStreak int
}

// isTracked reports whether the run is followed in polls: its terminal
// update has not been acknowledged yet.
func (r *trackedRun) isTracked() bool {
	return r.state == TrackingInFlight ||
		r.state == TrackingTerminalDelivered
}

// Stop asks Step to return a Done task. Two cases:
//
//   - A backend poll (or the wait before one) is in flight: abandon it
//     and exit. Do not ask the optimizer for another batch.
//   - The optimizer is producing suggestions for the outstanding
//     generation: apply that result, enqueue the suggestions once, then
//     exit.
func (s *Scheduler) Stop() {
	s.stopOnce.Do(func() { close(s.stop) })
}

// withStopCancel returns a child of ctx that is cancelled when Stop is
// requested. The cancelled call surfaces as Done through ctx.Done or
// doneFromError. cancel must be called so the watcher goroutine exits.
//
// Apply-result / enqueue still uses the session context, which this
// does not cancel.
func (s *Scheduler) withStopCancel(
	ctx context.Context,
) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(ctx)
	s.cancelOnStop(ctx, cancel)
	return ctx, cancel
}

// cancelOnStop cancels immediately if Stop was already requested;
// otherwise a goroutine waits for Stop or ctx to end.
func (s *Scheduler) cancelOnStop(ctx context.Context, cancel context.CancelFunc) {
	wait := func() {
		select {
		case <-s.stop:
			cancel()
		case <-ctx.Done():
		}
	}
	select {
	case <-s.stop:
		cancel()
	default:
		go wait()
	}
}

// Step implements TaskResolver: apply the previous task's result, wait one
// poll interval, and compute the next task.
func (s *Scheduler) Step(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	if result != nil {
		if done := s.applyResult(ctx, result); done != nil {
			return done
		}
	}

	// Stop cancels this context so sleep and polls abort; enqueue above
	// used the session context so in-flight suggestions are still
	// scheduled.
	ctx, cancel := s.withStopCancel(ctx)
	defer cancel()

	// Warm-start pages are delivered back to back; only steady-state
	// generations pace themselves.
	if !s.warmDone {
		return s.warmStartStep(ctx)
	}

	if done := s.sleep(ctx); done != nil {
		return done
	}
	return s.generationStep(ctx)
}

// sleep waits one poll interval plus the failure slowdown, returning a
// Done task if ctx is cancelled (session end or Stop) while waiting.
func (s *Scheduler) sleep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	if ctx.Err() != nil {
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
	}

	fire, stopTimer := s.timer(s.pollInterval + s.api.Slowdown())
	defer stopTimer()

	select {
	case <-fire:
		return nil
	case <-ctx.Done():
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
	}
}

// doneFromError maps a classified poll or enqueue failure onto a Done
// task, or returns nil if the loop should keep going.
//
// The API layer already recorded the failure in the backoff; this only
// decides whether the loop can continue.
func (s *Scheduler) doneFromError(
	ctx context.Context,
	err error,
) *spb.SweepSchedulerServerNextTaskResponse {
	// Cancellation is shutdown (Stop or the session ending), not a
	// backend failure. Deadlines go through Classify: a timed-out
	// call is transient, like any other request that got no response.
	if errors.Is(ctx.Err(), context.Canceled) ||
		errors.Is(err, context.Canceled) {
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
	}

	switch Classify(err) {
	case DispositionNotFound:
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
			"the sweep was deleted")
	case DispositionFatal:
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
			err.Error())
	default:
		if s.api.Exhausted() {
			return s.doneTask(
				spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				"too many consecutive errors; last: "+err.Error())
		}
		s.logger.Warn("scheduler: transient failure", "error", err)
		return nil
	}
}

// doneTask builds a Done task carrying any unreported discards.
func (s *Scheduler) doneTask(
	reason spb.SweepSchedulerServerDoneTask_Reason,
	message string,
) *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason:                   reason,
				Message:                  message,
				DiscardedOptimizerRunIds: s.takeDiscards(),
			},
		},
	}
}

// takeDiscards returns the accumulated discards and clears them: each
// discarded suggestion is reported exactly once.
func (s *Scheduler) takeDiscards() []string {
	discards := s.discards
	s.discards = nil
	return discards
}

// trackedRunCount is how many runs the loop still expects results from.
func (s *Scheduler) trackedRunCount() int {
	count := 0
	for _, run := range s.runs {
		if run.isTracked() {
			count++
		}
	}
	return count
}

// finishExhausted ends the sweep because the search space ran out.
func (s *Scheduler) finishExhausted(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.finishSweep(ctx)
	// No message: the reason alone already says it.
	return s.doneTask(
		spb.SweepSchedulerServerDoneTask_REASON_EXHAUSTED, "")
}

// finishSweep marks the sweep FINISHED, best-effort: the Done task is
// delivered either way, and a failed upsert only costs the state label.
func (s *Scheduler) finishSweep(ctx context.Context) {
	err := s.api.UpsertSweepState(ctx, s.sweepNodeID, sweepStateFinished)
	if err != nil {
		s.logger.Warn(
			"scheduler: failed to mark the sweep finished", "error", err)
	}
}

// SchedulerParams configures a Scheduler directly, bypassing settings
// and client construction. It is the test seam; production code goes
// through NewTaskResolverFactory.
type SchedulerParams struct {
	API    *SweepAPI
	Logger *observability.CoreLogger

	SweepNodeID string
	MetricKey   string

	BatchSize    int
	PollInterval time.Duration

	// Now stubs time; nil means time.Now.
	Now func() time.Time

	// Timer stubs the poll-interval wait; nil means a real timer.
	Timer func(d time.Duration) (<-chan time.Time, func())
}

// NewScheduler builds a Scheduler from explicit parameters.
func NewScheduler(params SchedulerParams) *Scheduler {
	if params.BatchSize <= 0 {
		params.BatchSize = defaultBatchSize
	}
	if params.PollInterval <= 0 {
		params.PollInterval = defaultPollInterval
	}
	if params.Now == nil {
		params.Now = time.Now
	}
	if params.Timer == nil {
		params.Timer = func(d time.Duration) (<-chan time.Time, func()) {
			timer := time.NewTimer(d)
			return timer.C, func() { timer.Stop() }
		}
	}

	return &Scheduler{
		api:    newTrackedAPI(params.API),
		logger: params.Logger,

		sweepNodeID:  params.SweepNodeID,
		metricKey:    params.MetricKey,
		batchSize:    params.BatchSize,
		pollInterval: params.PollInterval,

		stop:  make(chan struct{}),
		now:   params.Now,
		timer: params.Timer,

		runs:               make(map[string]*trackedRun),
		runsByName:         make(map[string]*trackedRun),
		warnedUnrecognized: make(map[string]bool),
	}
}

// NewTaskResolverFactory returns the factory the session broker uses to start
// scheduler sessions from client init requests.
func NewTaskResolverFactory(logger *observability.CoreLogger) TaskResolverFactory {
	return func(
		schedCtx context.Context,
		reqCtx context.Context,
		req *spb.SweepSchedulerClientInitRequest,
	) (TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
		sweepAPI, err := newSweepAPI(req, logger)
		if err != nil {
			return nil, nil, err
		}

		if err := sweepAPI.CheckLocalSchedulerSupported(reqCtx); err != nil {
			return nil, nil, err
		}

		facts, err := sweepAPI.FetchSweep(reqCtx)
		if err != nil {
			return nil, nil, err
		}

		metricKey, err := parseMetricKey(facts.Config)
		if err != nil {
			return nil, nil, err
		}

		scheduler := NewScheduler(SchedulerParams{
			API:          sweepAPI,
			Logger:       logger,
			SweepNodeID:  facts.NodeID,
			MetricKey:    metricKey,
			BatchSize:    int(req.BatchSize),
			PollInterval: secondsToDuration(req.PollIntervalSeconds),
		})

		return scheduler, &spb.SweepSchedulerServerInitResponse{
			SweepConfig:       facts.Config,
			DisplayName:       facts.DisplayName,
			ControllerRunName: facts.ControllerRunName,
		}, nil
	}
}

// newSweepAPI builds the backend client from the init request's settings.
func newSweepAPI(
	req *spb.SweepSchedulerClientInitRequest,
	logger *observability.CoreLogger,
) (*SweepAPI, error) {
	clientSettings := settings.From(req.Settings)

	baseURL, err := url.Parse(clientSettings.GetBaseURL())
	if err != nil {
		return nil, fmt.Errorf("scheduler: parsing base URL: %v", err)
	}

	credentialProvider, err := api.NewCredentialProvider(
		clientSettings, logger.Logger)
	if err != nil {
		return nil, fmt.Errorf("scheduler: reading credentials: %v", err)
	}

	gqlClient := api.NewGQLClient(
		api.WBBaseURL(baseURL),
		"", /*clientID*/
		credentialProvider,
		logger.Logger,
		&observability.Peeker{},
		clientSettings,
		clientSettings.GetExtraHTTPHeaders(),
	)

	return NewSweepAPI(
		gqlClient,
		featurechecker.New(gqlClient, logger),
		req.Entity,
		req.Project,
		req.SweepId,
	), nil
}

// secondsToDuration converts a request's seconds field; zero stays zero
// so NewScheduler applies its default.
func secondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
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
		if done := s.doneFromError(ctx, err); done != nil {
			return done
		}
		// Transient: deliver an empty task and try again next poll.
		return s.generationTask(nil, nil, 0)
	}
	s.noteBackendState(snapshot)

	if !sweepIsActive(snapshot.sweepState) {
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
			"the sweep is "+snapshot.sweepState)
	}
	if snapshot.sweepState == sweepStatePaused {
		return s.generationTask(nil, nil, 0)
	}

	s.observeUntrackedRuns(snapshot)

	updates, candidates := s.buildUpdates(ctx, snapshot)

	if s.exhausted {
		// Every scheduled run has reported its outcome, so the sweep is
		// done; asking again would only repeat the empty answer.
		if s.trackedRunCount() == 0 {
			return s.finishExhausted(ctx)
		}
		return s.generationTask(updates, candidates, 0)
	}
	return s.generationTask(updates, candidates, s.askBudget())
}

// generationTask assembles an generation task with any pending discards.
func (s *Scheduler) generationTask(
	updates []*spb.SweepSchedulerServerRunUpdate,
	pruneCandidates []string,
	askUpTo int,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.lastPruneCandidates = make(map[string]bool, len(pruneCandidates))
	for _, id := range pruneCandidates {
		s.lastPruneCandidates[id] = true
	}

	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Generation{
			Generation: &spb.SweepSchedulerServerGenerationTask{
				Updates:                  updates,
				AskUpTo:                  uint32(max(0, askUpTo)),
				PruneCandidates:          pruneCandidates,
				DiscardedOptimizerRunIds: s.takeDiscards(),
			},
		},
	}
}

// noteBackendState logs, every stagnantLogInterval, that polling has
// detected no significant change: the sweep's state and every row's
// name, state and summary are as the previous poll saw them. The
// cadence gives a stuck sweep — say, pending runs no agent picks up —
// a visible heartbeat to debug from.
func (s *Scheduler) noteBackendState(snapshot *pollSnapshot) {
	fingerprint := snapshotFingerprint(snapshot)
	now := s.now()

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

// snapshotFingerprint condenses a poll's observable state; two equal
// fingerprints mean polling saw no significant change. Rows are hashed
// in name order so backend ordering cannot masquerade as change.
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
// Untracked runs never count toward the batch: batch_size budgets only
// this scheduler's own runs. A reported run that turned alive
// again was resumed after its result was delivered; it cannot be
// re-told, because search strategies are append-only.
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
		if present {
			s.updateTrackedRunFromPoll(run, row)
		} else if !s.reapIfDeleted(ctx, run) {
			// Missing but not confirmed deleted: no update this poll.
			continue
		}

		if run.pruned && !runStateIsTerminal(run.runState) {
			s.nudgeStuckPrunedRun(ctx, run)
			continue
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
			Pruned: run.pruned,
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

// updateTrackedRunFromPoll applies one poll row to a tracked run, including the
// state reclassifications the optimizer should never have to know about.
func (s *Scheduler) updateTrackedRunFromPoll(run *trackedRun, row PollRun) {
	run.missingStreak = 0
	run.storageID = row.StorageID

	if row.State == "" {
		// The row was readable but stateless; twice in a row means the
		// run's record is broken and it will never progress.
		run.unknownStreak++
		if run.unknownStreak >= 2 {
			run.runState = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
		}
		return
	}
	run.unknownStreak = 0

	state := s.stateOrFailed(row.State)

	if state == spb.SweepRunState_SWEEP_RUN_STATE_FINISHED &&
		s.metricKey != "" && !summaryHasMetric(row.SummaryJSON, s.metricKey) {
		// A run that finished without logging the objective gave the
		// search nothing; report it failed so strategies do not treat
		// a missing value as a great one.
		s.logger.Warn(
			"scheduler: run finished without the sweep metric; "+
				"reporting it as failed",
			"run", run.name, "metric", s.metricKey)
		state = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
	}
	run.runState = state
}

// reapIfDeleted handles a tracked run absent from a complete poll and
// reports whether it was confirmed deleted and failed.
func (s *Scheduler) reapIfDeleted(
	ctx context.Context,
	run *trackedRun,
) bool {
	run.missingStreak++
	if run.missingStreak < 2 {
		return false
	}

	exists, err := s.api.ConfirmRunExists(ctx, run.name)
	if err != nil {
		s.logger.Warn(
			"scheduler: could not confirm a missing run's deletion",
			"run", run.name, "error", err)
		return false
	}
	if exists {
		// A pagination hiccup, not a deletion.
		run.missingStreak = 0
		return false
	}

	s.logger.Warn(
		"scheduler: run was deleted; reporting it as failed",
		"run", run.name)
	run.runState = spb.SweepRunState_SWEEP_RUN_STATE_FAILED
	return true
}

// nudgeStuckPrunedRun reissues StopRun once for a pruned run whose
// client is ignoring the stop flag.
func (s *Scheduler) nudgeStuckPrunedRun(
	ctx context.Context,
	run *trackedRun,
) {
	if run.stopRetried || s.now().Sub(run.stopIssued) <= stopGrace {
		return
	}
	run.stopRetried = true

	if _, err := s.api.StopRun(ctx, run.storageID); err != nil {
		s.logger.Error(
			"scheduler: failed to re-stop a pruned run",
			"run", run.name, "error", err)
	}
	s.logger.Warn(
		"scheduler: a pruned run is still running; it will stop "+
			"counting toward the batch if it keeps ignoring the stop",
		"run", run.name)
}

// askBudget is how many new suggestions the next ask may return.
func (s *Scheduler) askBudget() int {
	occupied := 0
	now := s.now()
	for _, run := range s.runs {
		if run.isTracked() && run.occupiesSlot(now, stopGrace) {
			occupied++
		}
	}
	return s.batchSize - occupied
}

// flattenWireConfig converts the backend's {param: {"value": v}} config
// form into the flat {param: v} form the protocol carries.
//
// Values that are not in the wrapped form pass through unchanged, and an
// unparseable config becomes an empty object: the optimizer already knows
// the configs of runs it proposed, so this only matters for adoption.
func flattenWireConfig(wireJSON string) string {
	if wireJSON == "" {
		return "{}"
	}

	var wire map[string]any
	if err := json.Unmarshal([]byte(wireJSON), &wire); err != nil {
		return "{}"
	}

	flat := make(map[string]any, len(wire))
	for name, param := range wire {
		if wrapped, ok := param.(map[string]any); ok {
			if value, ok := wrapped["value"]; ok {
				flat[name] = value
				continue
			}
		}
		flat[name] = param
	}

	encoded, err := json.Marshal(flat)
	if err != nil {
		return "{}"
	}
	return string(encoded)
}

// summaryHasMetric reports whether the summary JSON has a non-null value
// for the sweep's metric.
func summaryHasMetric(summaryJSON, metricKey string) bool {
	if summaryJSON == "" {
		return false
	}
	var summary map[string]any
	if err := json.Unmarshal([]byte(summaryJSON), &summary); err != nil {
		return false
	}
	value, ok := summary[metricKey]
	return ok && value != nil
}

// applyResult applies an acknowledged task result. A non-nil return ends
// the scheduler with that Done task.
func (s *Scheduler) applyResult(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	switch r := result.Result.(type) {
	case *spb.SweepSchedulerClientTaskResult_Error:
		s.logger.Error(
			"scheduler: the optimizer failed",
			"error", r.Error.Message,
			"traceback", r.Error.Traceback)
		// The sweep is left as-is so a fixed client can resume it.
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_OPTIMIZER_ERROR,
			r.Error.Message)

	case *spb.SweepSchedulerClientTaskResult_WarmStart:
		s.applyWarmStartResult(r.WarmStart)
		return nil

	case *spb.SweepSchedulerClientTaskResult_Generation:
		return s.applyGenerationResult(ctx, r.Generation)

	default:
		// A result with no payload answers a task with nothing to
		// report, such as an empty heartbeat generation.
		return nil
	}
}

// applyWarmStartResult merges one warm-start page's adoptions.
func (s *Scheduler) applyWarmStartResult(
	result *spb.SweepSchedulerClientWarmStartResult,
) {
	for wandbRunID, optimizerRunID := range result.Adoptions {
		if optimizerRunID == "" || s.runs[optimizerRunID] != nil {
			s.logger.Warn(
				"scheduler: dropping adoption with an empty or "+
					"duplicate optimizer run id",
				"run", wandbRunID, "id", optimizerRunID)
			// Report it like a dropped suggestion: the optimizer thinks
			// it adopted the run and would otherwise wait forever for
			// updates the scheduler will never send.
			s.discards = append(s.discards, optimizerRunID)
			continue
		}
		if run := s.runsByName[wandbRunID]; run != nil && run.isTracked() {
			// Adoption merging is idempotent per page; a redelivered
			// page's adoptions are already tracked.
			continue
		}

		run := &trackedRun{
			state:          TrackingInFlight,
			name:           wandbRunID,
			optimizerRunID: optimizerRunID,
			// The next poll refreshes the state; until then the run is
			// alive, which is why it was offered for adoption.
			runState: spb.SweepRunState_SWEEP_RUN_STATE_UNKNOWN,
		}
		s.runs[optimizerRunID] = run
		s.runsByName[wandbRunID] = run
	}

	for _, skipped := range result.Skipped {
		run := s.runsByName[skipped.WandbRunId]
		if run == nil {
			run = &trackedRun{name: skipped.WandbRunId}
			s.runsByName[skipped.WandbRunId] = run
		}
		run.state = TrackingRetired
		s.logger.Warn(
			"scheduler: the optimizer could not ingest a prior run; "+
				"excluding it",
			"run", skipped.WandbRunId, "error", skipped.Error)
	}
}

// applyGenerationResult applies tells, prunes and suggestions. A non-nil
// return ends the scheduler with that Done task.
func (s *Scheduler) applyGenerationResult(
	ctx context.Context,
	result *spb.SweepSchedulerClientGenerationResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	s.popDeliveredTerminals()
	s.popTellErrors(result.TellErrors)
	s.applyPrunes(ctx, result.Prune)

	if result.Terminate {
		s.finishSweep(ctx)
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_TERMINATED, "")
	}

	switch result.AskOutcome {
	case spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED:
		// Runs already scheduled still have results to report, and a
		// finished sweep stops the backend handing them to agents, so
		// wait for them instead of abandoning the last batch.
		s.exhausted = true
		if remaining := s.trackedRunCount(); remaining > 0 {
			s.logger.Info(
				"scheduler: search space exhausted; waiting for runs",
				"runs", remaining)
			return nil
		}
		return s.finishExhausted(ctx)

	case spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_SUGGESTED:
		return s.enqueueSuggestions(ctx, result.Suggestions)

	default:
		// Declined or not asked; nothing to schedule this generation.
		return nil
	}
}

// popDeliveredTerminals retires runs whose terminal update the client
// has now acknowledged, so a resumed run is noticed rather than
// re-told.
func (s *Scheduler) popDeliveredTerminals() {
	for _, run := range s.runs {
		if run.state == TrackingTerminalDelivered {
			run.state = TrackingRetired
			run.reported = true
		}
	}
}

// popTellErrors stops tracking runs the optimizer failed to ingest, so
// one poison run cannot fail the sweep on every poll.
func (s *Scheduler) popTellErrors(
	tellErrors []*spb.SweepSchedulerClientTellError,
) {
	if len(tellErrors) == 0 {
		return
	}

	for _, tellError := range tellErrors {
		run := s.runs[tellError.OptimizerRunId]
		if run == nil || !run.isTracked() {
			continue
		}
		s.logger.Warn(
			"scheduler: the optimizer could not ingest a run's "+
				"update; excluding the run",
			"run", run.name, "error", tellError.Message)
		// Retired without reported: the run is ignored for good and,
		// unlike a reported run that resumes, frees its batch slot so
		// the search can replace it.
		run.state = TrackingRetired
	}
}

// enqueueSuggestions schedules the optimizer's new runs. A non-nil
// return ends the scheduler with that Done task.
//
// Every suggestion that is not durably enqueued lands in the discard
// channel so the optimizer can release it; silently dropping one would
// leave the search counting a run that will never happen.
//
// A pending Stop does not skip this: graceful shutdown still tries once
// to enqueue the suggestions the client just produced. Step then
// observes stop on the next long wait (sleep or poll) and returns Done.
func (s *Scheduler) enqueueSuggestions(
	ctx context.Context,
	suggestions []*spb.SweepSchedulerClientRunSuggestion,
) *spb.SweepSchedulerServerNextTaskResponse {
	if len(suggestions) == 0 {
		return nil
	}

	// The suggestions were computed against an earlier poll; make sure
	// the sweep did not finish while the optimizer was thinking.
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
	case !sweepIsActive(facts.State):
		s.discardAll(suggestions)
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
			"the sweep is "+facts.State)
	case facts.State == sweepStatePaused:
		// Pausing is not terminal, but new runs must not start; the
		// optimizer gets these back through the discard channel and the
		// next asks are skipped until the sweep resumes.
		s.discardAll(suggestions)
		return nil
	}

	for i, suggestion := range suggestions {
		if done := s.enqueueOne(ctx, suggestion); done != nil {
			s.discardAll(suggestions[i:])
			return done
		}
	}
	return nil
}

// enqueueOne schedules a single suggestion. A failed enqueue ends the
// scheduler with an error, discarding the suggestion so the optimizer
// forgets it. A non-nil return ends the scheduler with that Done task.
func (s *Scheduler) enqueueOne(
	ctx context.Context,
	suggestion *spb.SweepSchedulerClientRunSuggestion,
) *spb.SweepSchedulerServerNextTaskResponse {
	id := suggestion.OptimizerRunId
	if id == "" {
		// Ids key the scheduler's run tracking, so an id-less
		// suggestion cannot be tracked.
		s.logger.Warn("scheduler: dropping suggestion with an empty id")
		s.discards = append(s.discards, id)
		return nil
	}
	if s.runs[id] != nil {
		s.logger.Warn(
			"scheduler: dropping suggestion with a duplicate "+
				"optimizer run id", "id", id)
		s.discards = append(s.discards, id)
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
		return nil
	}

	mintedID, err := s.api.EnqueueRun(ctx, s.sweepNodeID, wireConfig)
	if err != nil {
		// The discard rides the Done task so the optimizer still
		// forgets the suggestion.
		s.discards = append(s.discards, id)

		if ctx.Err() != nil {
			return s.doneTask(
				spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
		}
		if Classify(err) == DispositionNotFound {
			return s.doneTask(
				spb.SweepSchedulerServerDoneTask_REASON_SWEEP_NOT_FOUND,
				"the sweep was deleted")
		}

		s.logger.Error(
			"scheduler: failed to enqueue a suggestion",
			"id", id, "error", err)
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
			"failed to enqueue a suggestion: "+err.Error())
	}

	s.logger.Info("scheduler: enqueued run", "id", id)
	// The minted run is guaranteed to appear in the sweep as pending;
	// the next poll refreshes the placeholder state. One that never
	// appears was deleted by the user and is reaped like any other
	// tracked run missing from polls.
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

// occupiesSlot reports whether the run counts toward batch_size.
//
// A pruned run whose client ignored two stop requests no longer holds a
// slot, so a stuck run cannot stall the whole sweep.
func (r *trackedRun) occupiesSlot(now time.Time, stopGrace time.Duration) bool {
	if !runStateOccupiesSlot(r.runState) {
		return false
	}
	if r.pruned && r.stopRetried && now.Sub(r.stopIssued) > stopGrace {
		return false
	}
	return true
}

// applyPrunes stops the runs the optimizer pruned.
//
// Ids outside the candidates offered with the task are ignored, and stop
// failures are never loop-fatal: the run stays tracked (and prunable)
// until its terminal state arrives by poll. A pruned run gets one final
// terminal update and is excluded from tells and candidates until then.
func (s *Scheduler) applyPrunes(ctx context.Context, pruneIDs []string) {
	if len(pruneIDs) == 0 {
		return
	}

	for _, id := range pruneIDs {
		if !s.lastPruneCandidates[id] {
			continue
		}
		run := s.runs[id]
		if run == nil || !run.isTracked() ||
			run.pruned || runStateIsTerminal(run.runState) {
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
			s.logger.Error(
				"scheduler: the backend refused to stop a pruned run; "+
					"it may have already stopped",
				"run", run.name)
		}

		s.logger.Info("scheduler: stopping pruned run", "run", run.name)
		run.pruned = true
		run.stopIssued = s.now()
	}
}

// Sweep states the loop keeps scheduling under; any other state ends it.
const (
	sweepStateRunning = "RUNNING"
	sweepStatePending = "PENDING"
	sweepStatePaused  = "PAUSED"

	sweepStateFinished = "FINISHED"
)

// sweepIsActive reports whether the loop should keep driving the sweep.
func sweepIsActive(state string) bool {
	return state == sweepStateRunning ||
		state == sweepStatePending ||
		state == sweepStatePaused
}

// runStates maps the backend's run state strings onto the protocol enum.
//
// An unlisted string maps to UNKNOWN; stateOrFailed reports such runs
// as failed rather than guess what a state this scheduler predates
// means.
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

// stateOrFailed classifies a backend run state string, reporting a run
// in a state this scheduler does not recognize as failed: search
// strategies need clean alive-or-terminal semantics, and a run left
// alive on a guess could hold the sweep open forever.
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
//
// UNKNOWN, the pre-refresh placeholder of adopted runs, is
// non-terminal; PREEMPTED is both stopped and terminal.
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

// sweepConfig is the subset of a sweep's config the loop itself reads;
// everything else only matters to the client-side optimizer.
type sweepConfig struct {
	Metric struct {
		Name string `yaml:"name"`
	} `yaml:"metric"`
}

// parseMetricKey returns the sweep's objective metric name, or "" when
// the config declares none.
//
// A missing metric is allowed: it disables metric-history fetching and
// the FINISHED-without-metric reclassification rather than failing every
// poll.
func parseMetricKey(configYAML string) (string, error) {
	var config sweepConfig
	if err := yaml.Unmarshal([]byte(configYAML), &config); err != nil {
		return "", fmt.Errorf("scheduler: parsing sweep config: %v", err)
	}
	return config.Metric.Name, nil
}
