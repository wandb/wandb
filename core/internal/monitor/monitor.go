// Package monitor provides system resource monitoring capabilities.
package monitor

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/google/wire"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	defaultSamplingInterval = 15.0 * time.Second
)

// State definitions for the SystemMonitor.
const (
	StateStopped int32 = iota
	StateRunning
	StatePaused
)

// SystemMonitorProviders binds SystemMonitorFactory.
var SystemMonitorProviders = wire.NewSet(
	wire.Struct(new(SystemMonitorFactory), "*"),
)

// SystemMonitor publishes the system metrics streamed by the wandb-symon
// sidecar to the run and probes the compute environment.
type SystemMonitor struct {
	// The context for the system monitor.
	ctx    context.Context
	cancel context.CancelFunc

	// The state of the system monitor: stopped, running, or paused.
	state atomic.Int32

	// symon streams system metrics from the wandb-symon sidecar.
	symon *Symon

	// coreweave probes the CoreWeave compute environment, if any.
	coreweave *CoreWeaveMetadata

	// extraWork accepts outgoing messages for the run.
	extraWork runwork.ExtraWork

	// The in-memory metrics buffer for the system monitor.
	buffer *Buffer

	// runHandle is a handle to the eventually-initialized run.
	runHandle *runhandle.RunHandle

	// settings is the settings for the system monitor.
	settings *settings.Settings

	// The interval at which metrics are sampled.
	samplingInterval time.Duration

	// A logger for internal debug logging.
	logger *observability.CoreLogger

	// graphqlClient is the graphql client.
	graphqlClient graphql.Client

	// Unique identifier of the writer to the run.
	writerID sharedmode.ClientID

	// Information about the Git repository, if applicable.
	git *spb.GitRepoRecord
}

// SystemMonitorFactory constructs a SystemMonitor.
type SystemMonitorFactory struct {
	// A logger for internal debug logging.
	Logger *observability.CoreLogger

	// RunHandle is a handle to the eventually-initialized run.
	RunHandle *runhandle.RunHandle

	// Stream settings.
	Settings *settings.Settings

	// SymonResourceManager manages the wandb-symon sidecar process.
	SymonResourceManager *SymonResourceManager

	// graphqlClient is the GraphQL client to communicate with the W&B backend.
	GraphqlClient graphql.Client

	// Unique identifier of the writer to the run.
	WriterID sharedmode.ClientID
}

// New initializes and returns a new SystemMonitor instance.
//
// It builds the sidecar subscription from the settings and configures the
// metrics buffer.
func (f *SystemMonitorFactory) New(extraWork runwork.ExtraWork) *SystemMonitor {
	ctx, cancel := context.WithCancel(extraWork.BeforeEndCtx())
	sm := &SystemMonitor{
		ctx:              ctx,
		cancel:           cancel,
		runHandle:        f.RunHandle,
		settings:         f.Settings,
		logger:           f.Logger,
		extraWork:        extraWork,
		samplingInterval: defaultSamplingInterval,
		graphqlClient:    f.GraphqlClient,
		writerID:         f.WriterID,
	}

	if sm.settings.IsDisableStats() || sm.settings.IsDisableMachineInfo() {
		sm.logger.Debug("monitor: disabled")
		return sm
	}

	bufferSize := sm.settings.GetStatsBufferSize()
	// Initialize the buffer if a buffer size is provided.
	// A positive buffer size N indicates that only the last N samples will be kept in memory.
	// A value of -1 indicates that all sampled metrics will be kept in memory.
	if bufferSize != 0 {
		sm.buffer = NewBuffer(bufferSize)
	}

	if si := sm.settings.GetStatsSamplingInterval(); si != 0 {
		sm.samplingInterval = time.Duration(si * float64(time.Second))
	}
	sm.logger.Debug(fmt.Sprintf("monitor: sampling interval: %v", sm.samplingInterval))

	sm.initializeResources(f.SymonResourceManager)

	return sm
}

// initializeResources builds the sidecar subscription from the settings and
// the CoreWeave probe.
func (sm *SystemMonitor) initializeResources(symonResourceManager *SymonResourceManager) {
	sm.symon = NewSymon(sm.ctx, symonResourceManager, sm.logger)

	// CoreWeave compute environment metadata.
	if cwm, err := NewCoreWeaveMetadata(
		CoreWeaveMetadataParams{
			GraphqlClient: sm.graphqlClient,
			Logger:        sm.logger,
			RunHandle:     sm.runHandle,
			Settings:      sm.settings,
		},
	); cwm != nil {
		sm.coreweave = cwm
	} else if err != nil {
		sm.logger.CaptureError(
			"monitor",
			fmt.Errorf(
				"monitor: failed to initialize CoreWeave metadata resource: %v",
				err,
			),
		)
	}
}

// openMetricsFilters converts the x_stats_open_metrics_filters setting, a
// sequence of metric regexes or a mapping from metric regex to the label
// regexes its samples must match, to the sidecar's filters.
func openMetricsFilters(filters *spb.OpenMetricsFilters) []*spb.OpenMetricsFilter {
	var result []*spb.OpenMetricsFilter
	for _, regex := range filters.GetSequence().GetValue() {
		result = append(result, &spb.OpenMetricsFilter{MetricRegex: regex})
	}
	for regex, labels := range filters.GetMapping().GetValue() {
		result = append(result, &spb.OpenMetricsFilter{
			MetricRegex:  regex,
			LabelRegexes: labels.GetValue(),
		})
	}
	return result
}

// GetState returns the current state of the SystemMonitor.
func (sm *SystemMonitor) GetState() int32 {
	return sm.state.Load()
}

// probeExecutionContext collects information about the compute environment.
func (sm *SystemMonitor) probeExecutionContext() *spb.Record {
	sm.logger.Debug("monitor: probing execution environment")

	return &spb.Record{RecordType: &spb.Record_Environment{Environment: &spb.EnvironmentRecord{
		Os:            sm.settings.GetOS(),
		Python:        sm.settings.GetPython(),
		Host:          sm.settings.GetHostProcessorName(),
		Program:       sm.settings.GetProgram(),
		CodePath:      sm.settings.GetProgramRelativePath(),
		CodePathLocal: sm.settings.GetProgramRelativePathFromCwd(),
		Email:         sm.settings.GetEmail(),
		Root:          sm.settings.GetRootDir(),
		Username:      sm.settings.GetUserName(),
		Docker:        sm.settings.GetDockerImageName(),
		Executable:    sm.settings.GetExecutable(),
		Args:          sm.settings.GetArgs(),
		Colab:         sm.settings.GetColabURL(),
		StartedAt:     timestamppb.New(sm.settings.GetStartTime()),
		Git:           sm.git,
		Slurm:         slurmEnvVars(),

		WriterId: string(sm.writerID),
	}}}
}

// slurmEnvVars returns the SLURM_* environment variables keyed by their
// lowercased suffix, or nil when there are none.
func slurmEnvVars() map[string]string {
	var vars map[string]string
	for _, envVar := range os.Environ() {
		key, value, ok := strings.Cut(envVar, "=")
		if !ok {
			continue
		}
		if suffix, ok := strings.CutPrefix(key, "SLURM_"); ok {
			if vars == nil {
				vars = make(map[string]string)
			}
			vars[strings.ToLower(suffix)] = value
		}
	}
	return vars
}

// subscribeRequest describes the run's subscription to the sidecar: what
// to sample, how often and for whom.
func (sm *SystemMonitor) subscribeRequest() *spb.SubscribeRequest {
	request := &spb.SubscribeRequest{
		IntervalSeconds:         sm.samplingInterval.Seconds(),
		Pid:                     sm.settings.GetStatsPid(),
		GpuDeviceIds:            sm.settings.GetStatsGpuDeviceIds(),
		SubscriberId:            string(sm.writerID),
		TrackProcessTree:        sm.settings.GetStatsTrackProcessTree(),
		DiskPaths:               sm.settings.GetStatsDiskPaths(),
		DisableCgroup:           sm.settings.GetStatsNoCgroup(),
		OpenMetricsEndpoints:    sm.settings.GetStatsOpenMetricsEndpoints(),
		OpenMetricsFilters:      openMetricsFilters(sm.settings.GetStatsOpenMetricsFilters()),
		OpenMetricsHttpHeaders:  sm.settings.GetStatsOpenMetricsHeaders(),
		DcgmExporter:            sm.settings.GetStatsDcgmExporter(),
		NeuronMonitorConfigPath: sm.settings.GetStatsNeuronMonitorConfigPath(),
	}
	if sm.settings.GetStatsSelfUsage() {
		request.WandbPids = []int32{int32(os.Getpid())}
	}
	return request
}

// metadataRequest describes what the sidecar's probe should look at.
func (sm *SystemMonitor) metadataRequest() *spb.GetMetadataRequest {
	return &spb.GetMetadataRequest{
		DiskPaths:              sm.settings.GetStatsDiskPaths(),
		DcgmExporter:           sm.settings.GetStatsDcgmExporter(),
		OpenMetricsHttpHeaders: sm.settings.GetStatsOpenMetricsHeaders(),
	}
}

// probeResources merges the sidecar's probe with the CoreWeave
// environment metadata.
func (sm *SystemMonitor) probeResources() *spb.Record {
	sm.logger.Debug("monitor: probing resources")

	e := &spb.EnvironmentRecord{WriterId: string(sm.writerID)}

	var mu sync.Mutex
	var wg sync.WaitGroup
	for _, probe := range []func(context.Context) *spb.EnvironmentRecord{
		func(ctx context.Context) *spb.EnvironmentRecord {
			return sm.symon.Probe(ctx, sm.metadataRequest())
		},
		sm.coreweave.Probe,
	} {
		wg.Go(func() {
			defer func() {
				if err := recover(); err != nil {
					sm.logger.CaptureError(
						"monitor",
						fmt.Errorf("monitor: panic probing resource: %v", err),
					)
				}
			}()

			if rec := probe(sm.ctx); rec != nil {
				mu.Lock()
				proto.Merge(e, rec)
				mu.Unlock()
			}
		})
	}
	wg.Wait()

	// Overwrite auto-detected metadata with user-provided values.
	// TODO: move this to the relevant resources instead.
	if sm.settings.GetStatsCpuCount() > 0 {
		e.CpuCount = uint32(sm.settings.GetStatsCpuCount())
	}
	if sm.settings.GetStatsCpuLogicalCount() > 0 {
		e.CpuCountLogical = uint32(sm.settings.GetStatsCpuLogicalCount())
	}
	if sm.settings.GetStatsGpuCount() > 0 {
		e.GpuCount = uint32(sm.settings.GetStatsGpuCount())
	}
	if sm.settings.GetStatsGpuType() != "" {
		e.GpuType = sm.settings.GetStatsGpuType()
	}

	return &spb.Record{RecordType: &spb.Record_Environment{Environment: e}}
}

// Start begins resource monitoring.
//
// It is safe to call Start multiple times; only a stopped monitor will initiate.
func (sm *SystemMonitor) Start(git *spb.GitRepoRecord) {
	if sm == nil {
		return
	}

	if !sm.state.CompareAndSwap(StateStopped, StateRunning) {
		return // Already started or paused
	}

	sm.git = git

	if sm.settings.IsDisableStats() || sm.settings.IsDisableMachineInfo() {
		return
	}

	sm.logger.Debug("monitor: starting")
	sm.symon.Subscribe(sm.subscribeRequest(), sm.publish)
}

// Probe collects environment and resource information.
//
// This operation may take some time, so we perform it on a best-effort basis.
func (sm *SystemMonitor) Probe() {
	if !sm.settings.IsDisableMeta() && !sm.settings.IsDisableMachineInfo() &&
		sm.settings.IsPrimary() {
		go func() {
			sm.logger.Debug("monitor: collecting the environment and resource information")

			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.NoRequest(
					runwork.WorkFromRecord(sm.probeExecutionContext()),
				),
			)

			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.NoRequest(
					runwork.WorkFromRecord(sm.probeResources()),
				),
			)
		}()
	}
}

// Pause temporarily stops the monitoring process.
//
// Monitoring can be resumed later with the Resume method.
//
// Pause and Resume are used in notebook environments to ensure that
// metrics are only collected when a cell is running. We do it this way
// to prevent the overhead of starting and stopping the monitor for each cell.
func (sm *SystemMonitor) Pause() {
	if sm.state.CompareAndSwap(StateRunning, StatePaused) {
		sm.logger.Debug("monitor: pausing")
		sm.symon.Unsubscribe()
	}
}

// Resume restarts the monitoring process after it has been paused.
func (sm *SystemMonitor) Resume() {
	if sm.state.CompareAndSwap(StatePaused, StateRunning) {
		sm.logger.Debug("monitor: resuming")
		sm.symon.Subscribe(sm.subscribeRequest(), sm.publish)
	}
}

// publish buffers the sample in response and sends it to the run.
//
// It may block until ctx is done.
func (sm *SystemMonitor) publish(ctx context.Context, response *spb.SubscribeResponse) {
	metrics := response.GetRecord().GetStats()
	if len(metrics.GetItem()) == 0 {
		return // nothing to do
	}

	// Push metrics to the in-memory buffer when enabled.
	if sm.buffer != nil {
		sm.buffer.Push(metrics)
	}

	// Label for custom grouping of stats, e.g. per node in a multi-node run.
	if label := sm.settings.GetLabel(); label != "" {
		for _, item := range metrics.Item {
			item.Key = fmt.Sprintf("%s/l:%s", item.Key, label)
		}
	}

	record := &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: metrics,
		},
	}
	sm.extraWork.AddWorkOrCancel(
		ctx.Done(),
		runwork.NoRequest(runwork.WorkFromRecord(record)),
	)
}

// GetBuffer returns the current buffer of collected metrics.
//
// The buffer is a map of metric names to a slice of measurements - a list of
// (timestamp, value) pairs.
func (sm *SystemMonitor) GetBuffer() map[string][]Measurement {
	if sm == nil || sm.buffer == nil {
		return nil
	}
	return sm.buffer.GetMeasurements()
}

// Finish ends the subscription and releases the sidecar.
func (sm *SystemMonitor) Finish() {
	if sm == nil || sm.cancel == nil {
		return
	}
	if sm.state.Swap(StateStopped) == StateStopped {
		return // Already stopped
	}

	sm.logger.Debug("monitor: stopping")
	sm.cancel()
	sm.symon.Close()
	sm.logger.Debug("monitor: stopped")
}
