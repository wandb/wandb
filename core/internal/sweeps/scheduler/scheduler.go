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

	// minPollInterval is the floor below which a chosen interval is clamped.
	minPollInterval = 5 * time.Second

	// defaultBatchSize is used when the client chooses no batch size.
	defaultBatchSize = 1
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
	api    SweepAPI
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

	// runsByName indexes the prior runs warm start walked, so an adoption
	// can find the record that already counted toward the run cap.
	runsByName map[string]*trackedRun

	warnedUnrecognized map[string]bool
}

var _ TaskResolver = (*Scheduler)(nil)
var _ TaskResolverFactory = NewTaskResolverFactory(nil)

// NewScheduler builds a Scheduler from explicit parameters.
func NewScheduler(params SchedulerParams) *Scheduler {
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
		api:    params.API,
		logger: params.Logger,

		sweepNodeID:  params.SweepNodeID,
		metricKeys:   params.MetricKeys,
		batchSize:    params.BatchSize,
		pollInterval: params.PollInterval,
		runCap:       params.RunCap,

		stop:  make(chan struct{}),
		clock: params.Clock,

		runsByName:         make(map[string]*trackedRun),
		warnedUnrecognized: make(map[string]bool),
	}
}

// TrackingState is where a run stands in its lifecycle.
//
// A prior run walked by warm start starts out TrackingRetired: nothing
// adopts it until the optimizer says it did, which is the next slice.
type TrackingState int

const (
	TrackingInFlight TrackingState = iota

	// TrackingTerminalDelivered: the run's final update was delivered
	// but not acked yet.
	TrackingTerminalDelivered

	// TrackingDormant: the run ended without succeeding. It is still
	// polled, so a resume can be reported to the user, but it gets no
	// further updates and holds no batch slot.
	TrackingDormant

	// TrackingRetired: the scheduler will ignore this run.
	TrackingRetired
)

type trackedRun struct {
	state TrackingState

	// name is the run's W&B name.
	name string

	// finishedCounted means this run already counted toward finishedRunCount
	finishedCounted bool
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

// unimplementedDoneTask is what the generation phase returns until it
// has a real body.
func unimplementedDoneTask() *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason:  spb.SweepSchedulerServerDoneTask_REASON_FATAL_ERROR,
				Message: "scheduler: Step is not implemented",
			},
		},
	}
}

// Step implements TaskResolver: apply the previous task's result, wait one
// poll interval, and compute the next task.
//
// Results are ignored and the generation phase is unimplemented until
// the slices that add them land; warm start is the phase this change
// implements.
func (s *Scheduler) Step(
	ctx context.Context,
	result *spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	ctx, cancel := s.withStopCancel(ctx)
	defer cancel()

	if !s.warmDone {
		return s.warmStartStep(ctx)
	}

	if done := s.sleep(ctx); done != nil {
		return done
	}
	return unimplementedDoneTask()
}

// sleep waits one poll interval, returning a Done task if ctx is
// cancelled (session end or Stop) while waiting.
func (s *Scheduler) sleep(
	ctx context.Context,
) *spb.SweepSchedulerServerNextTaskResponse {
	if ctx.Err() != nil {
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
	}

	fire, stopTimer := s.clock.NewTimer(s.pollInterval)
	defer stopTimer()

	select {
	case <-fire:
		return nil
	case <-ctx.Done():
		return s.doneTask(
			spb.SweepSchedulerServerDoneTask_REASON_SHUTDOWN, "")
	}
}

// doneTask builds a Done task.
func (s *Scheduler) doneTask(
	reason spb.SweepSchedulerServerDoneTask_Reason,
	message string,
) *spb.SweepSchedulerServerNextTaskResponse {
	return &spb.SweepSchedulerServerNextTaskResponse{
		Task: &spb.SweepSchedulerServerNextTaskResponse_Done{
			Done: &spb.SweepSchedulerServerDoneTask{
				Reason:  reason,
				Message: message,
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
