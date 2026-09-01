package scheduler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
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

// realClock is the production Clock.
type realClock struct{}

func (realClock) Now() time.Time { return time.Now() }

func (realClock) NewTimer(d time.Duration) (<-chan time.Time, func()) {
	timer := time.NewTimer(d)
	return timer.C, func() { timer.Stop() }
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
	metricKey    string
	batchSize    int
	pollInterval time.Duration

	stopOnce sync.Once
	stop     chan struct{}

	// clock is real time in production; tests substitute a fake so
	// poll waits do not depend on the wall clock.
	clock Clock

	warmCursor *string
	warmDone   bool

	// runs is keyed by optimizer run id. Records are never removed, so
	// an id stays reserved for the scheduler's lifetime.
	runs map[string]*trackedRun

	// runsByName indexes the same records by W&B run name. Runs this
	// scheduler never scheduled or adopted appear only here.
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
	warnedForeign      bool
	warnedResumed      bool

	// Stagnation heartbeat; see noteBackendState.
	lastFingerprint string
	lastChange      time.Time
	lastStagnantLog time.Time
}

var _ TaskResolver = (*Scheduler)(nil)
var _ TaskResolverFactory = NewTaskResolverFactory(nil)

// TrackingState is where a run stands in its lifecycle.
//
// A suggestion passes through TrackingInFlight,
// TrackingTerminalDelivered and TrackingRetired in that order; before
// the scheduler has a record for it, it is merely proposed.
type TrackingState int

const (
	TrackingInFlight TrackingState = iota

	// TrackingTerminalDelivered: the run's final update was delivered
	// but not acked yet.
	TrackingTerminalDelivered

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

	// reported means the terminal update was acknowledged
	reported bool
}

// isTracked reports whether the run is followed in polls: its terminal
// update has not been acknowledged yet.
func (r *trackedRun) isTracked() bool {
	return r.state == TrackingInFlight ||
		r.state == TrackingTerminalDelivered
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

// SchedulerParams are the arguments to NewScheduler
type SchedulerParams struct {
	API    *SweepAPI
	Logger *observability.CoreLogger

	SweepNodeID string
	MetricKey   string

	BatchSize    int
	PollInterval time.Duration

	// Clock stubs time; nil means the real clock.
	Clock Clock
}

// NewScheduler builds a Scheduler from explicit parameters.
func NewScheduler(params SchedulerParams) *Scheduler {
	if params.BatchSize <= 0 {
		params.BatchSize = defaultBatchSize
	}
	if params.PollInterval <= 0 {
		params.PollInterval = defaultPollInterval
	}
	if params.Clock == nil {
		params.Clock = realClock{}
	}

	return &Scheduler{
		api:    newTrackedAPI(params.API),
		logger: params.Logger,

		sweepNodeID:  params.SweepNodeID,
		metricKey:    params.MetricKey,
		batchSize:    params.BatchSize,
		pollInterval: params.PollInterval,

		stop:  make(chan struct{}),
		clock: params.Clock,

		runs:               make(map[string]*trackedRun),
		runsByName:         make(map[string]*trackedRun),
		warnedUnrecognized: make(map[string]bool),
	}
}

// NewTaskResolverFactory returns the factory the session broker uses
// to start scheduler sessions.
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

func secondsToDuration(seconds float64) time.Duration {
	return time.Duration(seconds * float64(time.Second))
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
			// The optimizer thinks it adopted the run and would
			// otherwise wait forever for updates.
			s.discards = append(s.discards, optimizerRunID)
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

// popDeliveredTerminals retires runs whose terminal update the client
// acknowledged, so a resumed run is noticed rather than re-told.
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
}

// parseMetricKey returns the sweep's objective metric name, or ""
// when the config declares none: that disables history fetching and
// the FINISHED-without-metric reclassification rather than failing.
func parseMetricKey(configYAML string) (string, error) {
	var config sweepConfig
	if err := yaml.Unmarshal([]byte(configYAML), &config); err != nil {
		return "", fmt.Errorf("scheduler: parsing sweep config: %v", err)
	}
	return config.Metric.Name, nil
}
