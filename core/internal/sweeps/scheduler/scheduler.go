package scheduler

import (
	"context"
	"encoding/json"
	"fmt"
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
	// defaultPollInterval is used when the client chooses no interval.
	defaultPollInterval = 5 * time.Second

	// minPollInterval is the floor below which a chosen interval is clamped.
	minPollInterval = 5 * time.Second

	// defaultBatchSize is used when the client chooses no batch size.
	defaultBatchSize = 1

	// stagnantLogInterval is how often unchanged polls are logged.
	stagnantLogInterval = time.Minute
)

// Clock abstracts time so tests can control it directly instead of
// waiting on real timers and grace periods.
type Clock interface {
	// Now is the current time.
	Now() time.Time

	// NewTimer starts a timer that fires once after d, and returns a
	// function to release its resources; callers must call it even if
	// the timer already fired.
	NewTimer(d time.Duration) (<-chan time.Time, func())
}

// RealClock is the production Clock.
type RealClock struct{}

func (RealClock) Now() time.Time { return time.Now() }

func (RealClock) NewTimer(d time.Duration) (<-chan time.Time, func()) {
	timer := time.NewTimer(d)
	return timer.C, func() { timer.Stop() }
}

// SchedulerParams configures a new Scheduler.
type SchedulerParams struct {
	API    SweepAPI
	Logger *observability.CoreLogger

	SweepNodeID string
	MetricKeys  []string
	BatchSize   int
	RunCap      int

	PollInterval time.Duration

	// Clock is real time in production; tests substitute a fake so
	// poll waits do not depend on the wall clock.
	Clock Clock
}

// Scheduler drives one sweep; it implements TaskResolver.
//
// All state is mutated in Step, which the state machine serializes, so
// no field except the stop channel needs synchronization. Every run it
// touches is one trackedRun; see TrackingState for the lifecycle.
type Scheduler struct {
	api    *trackedAPI
	logger *observability.CoreLogger

	sweepNodeID  string
	metricKeys   []string
	batchSize    int
	pollInterval time.Duration

	stopOnce sync.Once
	stop     chan struct{}

	// clock is real time in production; tests substitute a fake so
	// poll waits do not depend on the wall clock.
	clock Clock

	warmCursor *string
	warmDone   bool

	runCap           int
	finishedRunCount int

	// runs is keyed by optimizer run id. Records are never removed, so
	// an id stays reserved for the scheduler's lifetime.
	runs map[string]*trackedRun

	// runOrder lists the ids in runs in the order they were created, so
	// polls and updates are assembled deterministically.
	runOrder []string

	// runsByName indexes the prior runs warm start walked, so an adoption
	// can find the record that already counted toward the run cap.
	// Generation polls key off runs instead.
	runsByName map[string]*trackedRun

	// discards holds ids of suggestions accepted but never durably
	// scheduled; reported on the next task.
	discards []string

	// lastPruneCandidates is the candidate set offered by the latest
	// generation task; prune ids outside it are ignored.
	lastPruneCandidates map[string]bool

	// exhausted stops further asks; the loop waits out the runs already
	// scheduled.
	exhausted bool

	warnedUnrecognized map[string]bool

	// Stagnation heartbeat; see noteBackendState.
	lastFingerprint string
	lastChange      time.Time
	lastStagnantLog time.Time
}

var _ TaskResolver = (*Scheduler)(nil)
var _ TaskResolverFactory = NewTaskResolverFactory(nil)

// NewScheduler builds a Scheduler from explicit parameters.
func NewScheduler(params SchedulerParams) *Scheduler {
	// A negative bound is a mistake in the sweep config; guessing what it
	// meant would silently cap or uncap the sweep, so it's dropped to
	// zero, which every bound reads as unset.
	if params.BatchSize < 0 {
		if params.Logger != nil {
			params.Logger.Warn(
				"scheduler: ignoring an invalid negative value",
				"setting", "batch size", "value", params.BatchSize)
		}
		params.BatchSize = 0
	}
	if params.RunCap < 0 {
		if params.Logger != nil {
			params.Logger.Warn(
				"scheduler: ignoring an invalid negative value",
				"setting", "run cap", "value", params.RunCap)
		}
		params.RunCap = 0
	}

	if params.BatchSize <= 0 {
		params.BatchSize = defaultBatchSize
	}
	if params.PollInterval <= 0 {
		params.PollInterval = defaultPollInterval
	} else if params.PollInterval < minPollInterval {
		if params.Logger != nil {
			params.Logger.Warn(
				"scheduler: poll interval below the floor, clamping",
				"requested", params.PollInterval, "floor", minPollInterval)
		}
		params.PollInterval = minPollInterval
	}
	if params.Clock == nil {
		params.Clock = RealClock{}
	}

	return &Scheduler{
		api:    newTrackedAPI(params.API),
		logger: params.Logger,

		sweepNodeID:  params.SweepNodeID,
		metricKeys:   params.MetricKeys,
		batchSize:    params.BatchSize,
		pollInterval: params.PollInterval,
		runCap:       params.RunCap,

		stop:  make(chan struct{}),
		clock: params.Clock,

		runs:               make(map[string]*trackedRun),
		runsByName:         make(map[string]*trackedRun),
		warnedUnrecognized: make(map[string]bool),
	}
}

// TrackingState is where a run stands in its lifecycle.
//
// A suggestion passes through TrackingInFlight and
// TrackingTerminalDelivered, then settles in TrackingDormant or
// TrackingRetired; before the scheduler has a record for it, it is
// merely proposed.
type TrackingState int

const (
	TrackingInFlight TrackingState = iota

	// TrackingTerminalDelivered: the run's final update was delivered
	// but not acked yet.
	TrackingTerminalDelivered

	// TrackingDormant: the run ended without succeeding. It is still
	// polled, so a resume can be reported to the user, but it gets no
	// further updates and holds no batch slot. See noteResumed for why
	// it cannot simply be told again.
	TrackingDormant

	// TrackingRetired: the scheduler will ignore this run.
	TrackingRetired
)

type trackedRun struct {
	state TrackingState

	// optimizerRunID is the id the optimizer tracks the run by.
	optimizerRunID string

	// name is the run's W&B name.
	name string

	// storageID is the run's GraphQL node id
	storageID string

	runState spb.SweepRunState

	// finishedCounted means this run already counted toward finishedRunCount
	finishedCounted bool

	// warnedResumed means the resume warning was already logged for it
	warnedResumed bool
}

// isTracked reports whether the run is reported to the optimizer: its
// terminal update has not been acknowledged yet.
func (r *trackedRun) isTracked() bool {
	return r.state == TrackingInFlight ||
		r.state == TrackingTerminalDelivered
}

// isWatched reports whether the run is read on every poll.
func (r *trackedRun) isWatched() bool {
	return r.state != TrackingRetired
}

// Stop asks Step to return a Done task
func (s *Scheduler) Stop() {
	s.stopOnce.Do(func() { close(s.stop) })
}

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

	ctx, cancel := s.withStopCancel(ctx)
	defer cancel()

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

	fire, stopTimer := s.clock.NewTimer(s.pollInterval + s.api.Slowdown())
	defer stopTimer()

	select {
	case <-fire:
		return nil
	case <-ctx.Done():
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
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

func (s *Scheduler) takeDiscards() []string {
	discards := s.discards
	s.discards = nil
	return discards
}

// track registers a run under its optimizer id, keeping runOrder in
// step with runs.
func (s *Scheduler) track(run *trackedRun) {
	s.runs[run.optimizerRunID] = run
	s.runOrder = append(s.runOrder, run.optimizerRunID)
}

// watchedRuns are the runs read on the next poll, in creation order.
func (s *Scheduler) watchedRuns() []*trackedRun {
	var watched []*trackedRun
	for _, id := range s.runOrder {
		if run := s.runs[id]; run.isWatched() {
			watched = append(watched, run)
		}
	}
	return watched
}

func (s *Scheduler) trackedRunCount() int {
	count := 0
	for _, run := range s.runs {
		if run.isTracked() {
			count++
		}
	}
	return count
}

// generationTask assembles a generation task with any discards.
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

// flattenWireConfig converts the backend's {param: {"value": v}}
// config form into the flat {param: v} form the protocol carries.
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

// summaryHasAllMetrics reports whether summaryJSON carries every one of
// metricKeys: a multi-objective sweep needs all its objectives to score
// a run, same as one objective for a single-objective sweep.
func summaryHasAllMetrics(summaryJSON string, metricKeys []string) bool {
	if summaryJSON == "" {
		return false
	}
	var summary map[string]any
	if err := json.Unmarshal([]byte(summaryJSON), &summary); err != nil {
		return false
	}
	for _, key := range metricKeys {
		if value, ok := summary[key]; !ok || value == nil {
			return false
		}
	}
	return true
}

// NewTaskResolverFactory returns the factory the session broker uses
// to start scheduler sessions.
func NewTaskResolverFactory(
	logger *observability.CoreLogger,
) TaskResolverFactory {
	return func(
		schedCtx context.Context,
		reqCtx context.Context,
		req *spb.SweepSchedulerClientInitRequest,
		sweepAPI SweepAPI,
	) (TaskResolver, *spb.SweepSchedulerServerInitResponse, error) {
		if err := sweepAPI.CheckLocalSchedulerSupported(reqCtx); err != nil {
			return nil, nil, err
		}

		facts, err := sweepAPI.FetchSweep(reqCtx)
		if err != nil {
			return nil, nil, err
		}

		cfg, err := parseSweepConfig(facts.Config)
		if err != nil {
			return nil, nil, err
		}

		scheduler := NewScheduler(SchedulerParams{
			API:          sweepAPI,
			Logger:       logger,
			SweepNodeID:  facts.NodeID,
			MetricKeys:   cfg.metricKeys(),
			BatchSize:    int(req.BatchSize),
			RunCap:       cfg.RunCap,
			PollInterval: secondsToDuration(req.PollIntervalSeconds),
		})

		return scheduler, &spb.SweepSchedulerServerInitResponse{
			SweepConfig:       facts.Config,
			DisplayName:       facts.DisplayName,
			ControllerRunName: facts.ControllerRunName,
		}, nil
	}
}

// newSweepAPIFromSettings opens the sweep's API against the backend the
// init request's settings name.
func newSweepAPIFromSettings(
	req *spb.SweepSchedulerClientInitRequest,
	logger *observability.CoreLogger,
) (SweepAPI, error) {
	if req.Settings == nil {
		return nil, fmt.Errorf("scheduler: the init request carries no settings")
	}
	clientSettings := settings.From(req.Settings)

	baseURL, err := url.Parse(clientSettings.GetBaseURL())
	if err != nil {
		return nil, fmt.Errorf("scheduler: parsing base URL: %w", err)
	}

	credentialProvider, err := api.NewCredentialProvider(
		clientSettings, logger.Logger)
	if err != nil {
		return nil, fmt.Errorf("scheduler: reading credentials: %w", err)
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

func secondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
}

// applyResult applies an acknowledged task result. A non-nil return ends
// the scheduler with that Done task.
func (s *Scheduler) applyResult(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	switch r := result.Result.(type) {
	case *spb.SweepSchedulerClientTaskResult_Error:
		s.recordFatalError(phaseOptimizer, r.Error.Message)
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
	// Sorted so that runOrder, and with it the order of every later
	// poll and task, does not depend on map iteration.
	for _, wandbRunID := range slices.Sorted(maps.Keys(result.Adoptions)) {
		optimizerRunID := result.Adoptions[wandbRunID]

		// Dropped, but never reported as a discard: the id names a run
		// this scheduler already tracks, and the client forgets
		// discarded ids before applying the task's updates, so
		// reporting it would drop that run from the optimizer and make
		// its own update in the same task fail.
		if s.runs[optimizerRunID] != nil {
			s.logger.Warn(
				"scheduler: dropping an adoption whose optimizer run id "+
					"is already in use",
				"run", wandbRunID, "id", optimizerRunID)
			continue
		}
		if run := s.runsByName[wandbRunID]; run != nil && run.isTracked() {
			// Already tracked: adopted on an earlier page, or scheduled
			// by this scheduler.
			continue
		}

		run := &trackedRun{
			state:          TrackingInFlight,
			name:           wandbRunID,
			optimizerRunID: optimizerRunID,
			// Placeholder until the next poll; UNKNOWN is not terminal.
			runState: spb.SweepRunState_SWEEP_RUN_STATE_UNKNOWN,
		}
		s.track(run)
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
			spb.SweepSchedulerServerDoneTask_REASON_SWEEP_FINISHED,
			"the optimizer ended the sweep")
	}

	switch result.AskOutcome {
	case spb.SweepSchedulerClientGenerationResult_ASK_OUTCOME_EXHAUSTED:
		// Finishing the sweep now would stop the backend handing the
		// scheduled runs to agents, so wait for them.
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

// popDeliveredTerminals settles runs whose terminal update the client
// acknowledged. Only one that finished successfully is done with for
// good, since its result cannot improve; any other ending goes dormant,
// where a resume is still worth reporting to the user.
func (s *Scheduler) popDeliveredTerminals() {
	for _, run := range s.runs {
		if run.state != TrackingTerminalDelivered {
			continue
		}
		if run.runState == spb.SweepRunState_SWEEP_RUN_STATE_FINISHED {
			run.state = TrackingRetired
		} else {
			run.state = TrackingDormant
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
		// Retired without reported: unlike a reported run that resumes,
		// this frees the batch slot so the search can replace it.
		run.state = TrackingRetired
	}
}

// sweepConfig is the subset of a sweep's config the loop itself reads;
// everything else only matters to the client-side optimizer.
type sweepConfig struct {
	Metric struct {
		Name string `yaml:"name"`
	} `yaml:"metric"`

	// Metrics names a multi-objective sweep's objectives; a
	// single-objective sweep names its one objective in Metric instead.
	Metrics []struct {
		Name string `yaml:"name"`
	} `yaml:"metrics"`

	RunCap int `yaml:"run_cap"`
}

// parseSweepConfig returns the sweep's objective metric name(s) and run
// cap.
//
// Every objective must be named: the loop reads each one out of a run's
// summary to report it, so an unnamed one would search against fewer
// objectives than the sweep declares. A run cap of 0 means the sweep is
// uncapped.
func parseSweepConfig(configYAML string) (*sweepConfig, error) {
	var cfg sweepConfig
	if err := yaml.Unmarshal([]byte(configYAML), &cfg); err != nil {
		return nil, fmt.Errorf("scheduler: parsing sweep config: %w", err)
	}

	for i, metric := range cfg.Metrics {
		if metric.Name == "" {
			return nil, fmt.Errorf(
				"scheduler: the sweep config's metrics[%d] has no name", i)
		}
	}
	if len(cfg.Metrics) > 0 && cfg.Metric.Name != "" {
		return nil, fmt.Errorf(
			"scheduler: the sweep config sets both metric and metrics")
	}
	if len(cfg.Metrics) == 0 && cfg.Metric.Name == "" {
		return nil, fmt.Errorf(
			"scheduler: the sweep config names no objective metric")
	}
	return &cfg, nil
}

// metricKeys names the sweep's objective metrics, in config order: a
// multi-objective sweep's `metrics`, or else its single `metric`.
func (cfg *sweepConfig) metricKeys() []string {
	if len(cfg.Metrics) > 0 {
		keys := make([]string, 0, len(cfg.Metrics))
		for _, metric := range cfg.Metrics {
			keys = append(keys, metric.Name)
		}
		return keys
	}
	return []string{cfg.Metric.Name}
}
