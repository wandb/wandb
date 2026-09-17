package scheduler

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
// Step and Stop are unimplemented placeholders: the polling and
// optimizer loop that gives them a real body lands on top of this
// contract in a later change.
type Scheduler struct {
	params SchedulerParams
}

var _ TaskResolver = (*Scheduler)(nil)

// NewScheduler constructs a Scheduler from params.
func NewScheduler(params SchedulerParams) *Scheduler {
	return &Scheduler{params: params}
}

// unimplementedDoneTask is what Step returns until it has a real body.
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

// Step is unimplemented; it always returns a Done task.
func (s *Scheduler) Step(
	context.Context,
	*spb.SweepSchedulerClientTaskResult,
) *spb.SweepSchedulerServerNextTaskResponse {
	return unimplementedDoneTask()
}

// Stop is unimplemented; Step never blocks long enough to need one.
func (s *Scheduler) Stop() {}

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
		return nil, fmt.Errorf("scheduler: parsing sweep config: %v", err)
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
