// Package monitor provides system resource monitoring capabilities.
package monitor

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/google/wire"
	"golang.org/x/sync/errgroup"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"google.golang.org/protobuf/types/known/timestamppb"

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

// SystemMonitorProviders bind SystemMonitorParams and NewSystemMonitor.
var SystemMonitorProviders = wire.NewSet(
	wire.Struct(new(SystemMonitorParams), "*"),
	NewSystemMonitor,
)

// Resource defines the interface for system resources to be monitored.
type Resource interface {
	Sample() (*spb.StatsRecord, error)
	Probe(ctx context.Context) *spb.EnvironmentRecord
}

// SystemMonitor is responsible for monitoring system metrics across various resources.
type SystemMonitor struct {
	// The context for the system monitor.
	ctx    context.Context
	cancel context.CancelFunc

	// The wait group for the system monitor.
	wg sync.WaitGroup

	// The state of the system monitor: stopped, running, or paused.
	state atomic.Int32

	// The list of resources to monitor.
	resources []Resource

	// extraWork accepts outgoing messages for the run.
	extraWork runwork.ExtraWork

	// The in-memory metrics buffer for the system monitor.
	buffer *Buffer

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
}

type SystemMonitorParams struct {
	Ctx context.Context

	// A logger for internal debug logging.
	Logger *observability.CoreLogger

	// Stream settings.
	Settings *settings.Settings

	// Extrawork accepts outgoing messages for the run.
	ExtraWork runwork.ExtraWork

	// GpuResourceManager manages costly resources used for GPU metrics.
	GpuResourceManager *GPUResourceManager

	// graphqlClient is the GraphQL client to communicate with the W&B backend.
	GraphqlClient graphql.Client

	// Unique identifier of the writer to the run.
	WriterID sharedmode.ClientID
}

// NewSystemMonitor initializes and returns a new SystemMonitor instance.
//
// It sets up resources based on provided settings and configures the metrics buffer.
func NewSystemMonitor(params SystemMonitorParams) *SystemMonitor {
	if params.Ctx == nil {
		params.Ctx = context.Background()
	}
	ctx, cancel := context.WithCancel(params.Ctx)
	sm := &SystemMonitor{
		ctx:              ctx,
		cancel:           cancel,
		wg:               sync.WaitGroup{},
		settings:         params.Settings,
		logger:           params.Logger,
		extraWork:        params.ExtraWork,
		samplingInterval: defaultSamplingInterval,
		graphqlClient:    params.GraphqlClient,
		writerID:         params.WriterID,
	}

	if sm.settings.IsDisableStats() {
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

	sm.initializeResources(params.GpuResourceManager)

	return sm
}

// initializeResources sets up the resources to be monitored based on the provided settings.
func (sm *SystemMonitor) initializeResources(gpuResourceManager *GPUResourceManager) {
	pid := sm.settings.GetStatsPid()
	samplingInterval := sm.settings.GetStatsSamplingInterval()
	neuronMonitorConfigPath := sm.settings.GetStatsNeuronMonitorConfigPath()
	gpuDeviceIds := sm.settings.GetStatsGpuDeviceIds()

	if system := NewSystem(
		SystemParams{
			Pid:              pid,
			TrackProcessTree: sm.settings.GetStatsTrackProcessTree(),
			DiskPaths:        sm.settings.GetStatsDiskPaths(),
		},
	); system != nil {
		sm.resources = append(sm.resources, system)
	}

	if gpu, err := NewGPU(gpuResourceManager, pid, gpuDeviceIds); gpu != nil {
		sm.resources = append(sm.resources, gpu)
	} else if err != nil {
		sm.logger.CaptureError(
			fmt.Errorf("monitor: failed to initialize GPU resource: %v", err))
	}

	if tpu := NewTPU(); tpu != nil {
		sm.resources = append(sm.resources, tpu)
	}

	if trainium := NewTrainium(sm.logger, pid, samplingInterval, neuronMonitorConfigPath); trainium != nil {
		sm.resources = append(sm.resources, trainium)
	}

	// CoreWeave compute environment metadata.
	if cwm, err := NewCoreWeaveMetadata(
		CoreWeaveMetadataParams{
			GraphqlClient: sm.graphqlClient,
			Logger:        sm.logger,
			Entity:        sm.settings.GetEntity(),
			BaseURL:       sm.settings.GetStatsCoreWeaveMetadataBaseURL(),
			Endpoint:      sm.settings.GetStatsCoreWeaveMetadataEndpoint(),
		},
	); cwm != nil {
		sm.resources = append(sm.resources, cwm)
	} else if err != nil {
		sm.logger.CaptureError(
			fmt.Errorf("monitor: failed to initialize CoreWeave metadata resource: %v", err))
	}

	// DCGM Exporter.
	if url := sm.settings.GetStatsDcgmExporter(); url != "" {
		params := DCGMExporterParams{
			URL:     url,
			Headers: sm.settings.GetStatsOpenMetricsHeaders(),
			Logger:  sm.logger,
		}
		if de := NewDCGMExporter(params); de != nil {
			sm.resources = append(sm.resources, de)
		}
	}

	// OpenMetrics endpoints to monitor.
	if endpoints := sm.settings.GetStatsOpenMetricsEndpoints(); endpoints != nil {
		for name, url := range endpoints {
			filters := sm.settings.GetStatsOpenMetricsFilters()
			headers := sm.settings.GetStatsOpenMetricsHeaders()
			if om := NewOpenMetrics(sm.logger, name, url, filters, headers, nil); om != nil {
				sm.resources = append(sm.resources, om)
			}
		}
	}
}

// marshal constructs a StatsRecord protobuf message from the provided stats map and timestamp.
func marshal(
	stats map[string]any,
	timeStamp *timestamppb.Timestamp,
) *spb.StatsRecord {
	statsItems := make([]*spb.StatsItem, 0, len(stats))
	for k, v := range stats {
		jsonData, err := simplejsonext.Marshal(v)
		if err != nil {
			continue
		}
		key := k
		statsItems = append(statsItems, &spb.StatsItem{
			Key:       key,
			ValueJson: string(jsonData),
		})
	}

	return &spb.StatsRecord{
		StatsType: spb.StatsRecord_SYSTEM,
		Timestamp: timeStamp,
		Item:      statsItems,
	}
}

// GetState returns the current state of the SystemMonitor.
func (sm *SystemMonitor) GetState() int32 {
	return sm.state.Load()
}

// probeExecutionContext collects information about the compute environment.
func (sm *SystemMonitor) probeExecutionContext(git *spb.GitRepoRecord) *spb.Record {
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
		Git:           git,

		WriterId: string(sm.writerID),
	}}}
}

// probeResources gathers system information from all resources and merges their metadata.
func (sm *SystemMonitor) probeResources() *spb.Record {
	sm.logger.Debug("monitor: probing resources")

	e := &spb.EnvironmentRecord{WriterId: string(sm.writerID)}

	g, gctx := errgroup.WithContext(sm.ctx)
	var mu sync.Mutex

	for _, resource := range sm.resources {
		g.Go(func() error {
			defer func() {
				if err := recover(); err != nil {
					sm.logger.CaptureError(fmt.Errorf("monitor: panic probing resource: %v", err))
				}
			}()

			if gctx.Err() != nil {
				return nil
			}

			if rec := resource.Probe(gctx); rec != nil {
				mu.Lock()
				proto.Merge(e, rec)
				mu.Unlock()
			}
			return nil
		})
	}

	_ = g.Wait()

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

// Start begins the monitoring process for all resources and probes system information.
//
// It is safe to call Start multiple times; only a stopped monitor will initiate.
func (sm *SystemMonitor) Start(git *spb.GitRepoRecord) {
	if sm == nil {
		return
	}

	if !sm.state.CompareAndSwap(StateStopped, StateRunning) {
		return // Already started or paused
	}

	// Probe the environment and resource metadata.
	if !sm.settings.IsDisableMeta() && !sm.settings.IsDisableMachineInfo() && sm.settings.IsPrimary() {
		sm.extraWork.AddWorkOrCancel(
			sm.ctx.Done(),
			runwork.WorkFromRecord(
				sm.probeExecutionContext(git),
			),
		)
		go func() {
			// This operation may take some time, so we perform it on a best-effort basis.
			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.WorkFromRecord(
					sm.probeResources(),
				),
			)
		}()
	}

	// Start collecting metrics.
	if !sm.settings.IsDisableStats() && !sm.settings.IsDisableMachineInfo() {
		sm.logger.Debug("monitor: starting")
		for _, resource := range sm.resources {
			sm.wg.Add(1)
			go sm.monitorResource(resource)
		}
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
	}
}

// Resume restarts the monitoring process after it has been paused.
func (sm *SystemMonitor) Resume() {
	if sm.state.CompareAndSwap(StatePaused, StateRunning) {
		sm.logger.Debug("monitor: resuming")
	}
}

// monitorResource handles the monitoring loop for a single resource.
//
// It handles sampling, aggregation, and reporting of metrics
// and is meant to run in its own goroutine.
func (sm *SystemMonitor) monitorResource(resource Resource) {
	if resource == nil {
		sm.wg.Done()
		return
	}

	// recover from panic and log the error
	defer func() {
		sm.wg.Done()
		if err := recover(); err != nil {
			if resource != nil {
				sm.logger.CaptureError(fmt.Errorf("monitor: panic: %v", err))
			}
		}
	}()

	// Create a ticker that fires every `samplingInterval` seconds
	ticker := time.NewTicker(sm.samplingInterval)
	defer ticker.Stop()

	for {
		select {
		case <-sm.ctx.Done():
			return
		case <-ticker.C:
			if sm.state.Load() != StateRunning {
				continue // Skip work when not running
			}

			metrics, err := resource.Sample()
			if err != nil {
				sm.logger.CaptureError(fmt.Errorf("monitor: error sampling metrics: %v", err))
				continue
			}

			if metrics == nil || len(metrics.Item) == 0 {
				continue // nothing to do
			}

			// Push metrics to the buffer
			sm.buffer.Push(metrics)

			// Label for custom grouping of stats, e.g. per node in a multi-node run.
			if label := sm.settings.GetLabel(); label != "" {
				for _, item := range metrics.Item {
					item.Key = fmt.Sprintf("%s/l:%s", item.Key, label)
				}
			}

			// publish metrics
			record := &spb.Record{
				RecordType: &spb.Record_Stats{
					Stats: metrics,
				},
				Control: &spb.Control{AlwaysSend: true},
			}
			sm.extraWork.AddWorkOrCancel(
				sm.ctx.Done(),
				runwork.WorkFromRecord(record),
			)
		}
	}

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

// Finish stops the monitoring process and performs necessary cleanup.
//
// NOTE: resource.Close is a potentially expensive operation.
func (sm *SystemMonitor) Finish() {
	if sm == nil || sm.cancel == nil {
		return
	}
	if sm.state.Swap(StateStopped) == StateStopped {
		return // Already stopped
	}

	sm.logger.Debug("monitor: stopping")

	// signal to stop monitoring the resources
	sm.cancel()
	// wait for all resources to stop monitoring
	sm.wg.Wait()
	// close the resources, if they require any cleanup
	for _, resource := range sm.resources {
		if closer, ok := resource.(interface{ Close() }); ok {
			closer.Close()
		}
	}
	sm.logger.Debug("monitor: stopped")
}
