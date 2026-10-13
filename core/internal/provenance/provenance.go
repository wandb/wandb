package provenance

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/provenance/platform"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/version"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const maxBufferedBytes = 4 << 20
const queueCapacity = 1024

type EmitterParams struct {
	FilesDir string
	WriterID string
	// Level is the collection level from settings; start requests must match it.
	Level int32
	// Work receives file registrations and, on Terminate, a synthetic exit record.
	Work runwork.ExtraWork
	Done <-chan struct{}
	// Tick is the background flush and sampling cadence; zero disables the loop.
	Tick    time.Duration
	Runtime func() (time.Duration, bool)
	Host    HostPaths
	Now     func() time.Time
}

type DrainResult struct {
	Files   *spb.FilesRecord
	Quality Quality
}

type Emitter struct {
	mu sync.Mutex
	// io serializes flushes and drain so file writes run outside mu in order.
	io                 sync.Mutex
	config             StartConfig
	filesDir           string
	writerID           string
	level              int32
	work               runwork.ExtraWork
	done               <-chan struct{}
	tick               time.Duration
	stop               chan struct{}
	loopDone           chan struct{}
	writes             []pendingWrite
	runtime            func() (time.Duration, bool)
	host               HostPaths
	now                func() time.Time
	active             bool
	stopped            bool
	collectionDisabled bool
	quality            Quality
	queue              [][]byte
	queuedBytes        int
	chunk              bytes.Buffer
	chunkStarted       time.Time
	startedAt          time.Time
	sequence           int
	lastMonotonic      int64
	lastDocuments      time.Time
	pending            map[string]spb.FilesItem_PolicyType
	records            map[string]int64
	manifest           Manifest
	redactor           *Redactor
	platform           platform.Adapter
	environment        *spb.EnvironmentRecord
	latest             *spb.StatsRecord
	boundUUID          string
	gpuIDs             map[string]string
	gpuDevices         map[string]*Device
	gpuBound           bool
	lastSample         time.Time
	backoff            bool
	pressureSamples    int
	pythonCPU          int64
	pythonDrops        int64
	exit               *Exit
	transport          *platform.TransportEvidence
}

// running holds emitters between Start and Drain so Terminate can reach their streams.
var running = struct {
	sync.Mutex
	emitters map[*Emitter]struct{}
}{emitters: map[*Emitter]struct{}{}}

func NewEmitter(p *EmitterParams) *Emitter {
	now := p.Now
	if now == nil {
		now = time.Now
	}
	return &Emitter{
		filesDir: p.FilesDir,
		writerID: p.WriterID,
		level:    p.Level,
		work:     p.Work,
		done:     p.Done,
		tick:     p.Tick,
		stop:     make(chan struct{}),
		runtime:  p.Runtime,
		host:     p.Host,
		now:      now,
		pending:  make(map[string]spb.FilesItem_PolicyType),
		records:  make(map[string]int64),
	}
}

// Handshake validates a writer's start request and starts the emitter with the core writer ID.
func (e *Emitter) Handshake(request *spb.ProvenanceStartRequest) *spb.ProvenanceStartResponse {
	response := &spb.ProvenanceStartResponse{ProtocolVersion: 2}
	switch {
	case request.GetProtocolVersion() != 2:
		response.Reason = "protocol_mismatch"
	case e == nil:
		response.Reason = "disabled"
	case request.GetLevel() > 1 || int32(request.GetLevel()) != e.level:
		response.Reason = "level_mismatch"
	}
	if response.Reason != "" {
		return response
	}
	config := StartConfig{
		WriterID:     e.writerID,
		RunID:        request.RunId,
		Level:        int(request.Level),
		Rank:         int(request.Rank),
		LocalRank:    int(request.LocalRank),
		NodeRank:     int(request.NodeRank),
		Attempt:      int(request.Attempt),
		Primary:      request.Primary,
		IdentityJSON: request.IdentityJson,
	}
	if err := e.Start(config); err != nil {
		response.Reason = err.Error()
		return response
	}
	response.Accepted = true
	response.WriterId = e.writerID
	return response
}

// SetEnvironment supplies probed accelerator metadata used to map GPU stats to the bound device.
func (e *Emitter) SetEnvironment(environment *spb.EnvironmentRecord) {
	if e == nil || environment == nil {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.environment = environment
}

// SetExit records the writer's exit code and terminal reason for the final manifest; the first call wins.
func (e *Emitter) SetExit(exitCode int32, reason string) {
	if e == nil {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.exit == nil {
		e.exit = &Exit{Code: exitCode, Reason: reason}
	}
}

// Terminate sends an exit record with exitCode to every started emitter's stream and waits up to timeout for its uploads.
func Terminate(timeout time.Duration, exitCode int32) {
	running.Lock()
	emitters := slices.Collect(maps.Keys(running.emitters))
	running.Unlock()
	if len(emitters) == 0 {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	var wg sync.WaitGroup
	for _, e := range emitters {
		e.SetExit(exitCode, "terminated")
		wg.Go(func() { e.terminate(ctx, exitCode) })
	}
	wg.Wait()
}

func (e *Emitter) terminate(ctx context.Context, exitCode int32) {
	if e.work == nil {
		return
	}
	requestCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	request := runwork.NewRequest("", requestCtx, cancel, make(chan *spb.ServerResponse, 1))
	exit := &spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: exitCode}}}
	if e.work.AddWorkOrCancel(
		ctx.Done(),
		runwork.Work{WorkImpl: runwork.WorkFromRecord(exit), Request: request},
	) {
		<-requestCtx.Done()
	}
}

func (e *Emitter) Start(config StartConfig) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.stopped {
		return errors.New("writer_finished")
	}
	if e.active {
		return errors.New("already_started")
	}
	if !config.valid() {
		return errors.New("invalid_identity")
	}
	e.config = config
	e.config.Primary = config.Primary && config.Rank == 0
	e.config.IdentityJSON = nil
	key, keyStatus := redactionKey()
	e.redactor = NewRedactor(key)
	if e.host.SysRoot != "" {
		e.platform = platform.New(
			platform.Config{
				SysRoot:   e.host.SysRoot,
				Pseudonym: e.redactor.Pseudonym,
				KeyReason: keyStatus.Reason,
			},
		)
	}
	e.gpuIDs = map[string]string{}
	e.gpuDevices = map[string]*Device{}
	e.chunkStarted = e.now()
	e.startedAt = e.chunkStarted
	e.manifest = Manifest{
		Header:            e.header("manifest"),
		Level:             config.Level,
		LocalRank:         config.LocalRank,
		NodeRank:          config.NodeRank,
		PrivacyPolicy:     "pseudonymous-1",
		SDKVersion:        version.Version,
		Capabilities:      map[string]Capability{},
		SamplingIntervalS: 15,
		ChunkIntervalS:    300,
	}
	e.manifest.Capabilities["identity_join"] = keyStatus
	e.manifest.Build, e.manifest.Capabilities["build_identity"] = buildIdentity()
	e.manifest.Capabilities["pricing"] = Capability{Status: "unavailable", Reason: "not_provided"}
	e.manifest.JobID, _ = e.redactor.Pseudonym("job", config.RunID)
	var identity struct {
		WorldSize *int   `json:"world_size"`
		Scheduler string `json:"scheduler"`
	}
	if len(config.IdentityJSON) <= 64<<10 && json.Unmarshal(config.IdentityJSON, &identity) == nil {
		if identity.WorldSize != nil && *identity.WorldSize > 0 {
			e.manifest.WorldSize = identity.WorldSize
		}
		if slices.Contains([]string{"torchrun", "slurm", "mpi"}, identity.Scheduler) {
			e.manifest.Scheduler = identity.Scheduler
		}
	}
	if err := e.documents(false); err != nil {
		e.stopped = true
		return err
	}
	writes := e.writes
	e.writes = nil
	results := e.writeFiles(writes)
	for _, result := range results {
		if result.err != nil && !errors.Is(result.err, errSkipped) {
			e.stopped = true
			return result.err
		}
	}
	e.register(writes, results)
	e.active = true
	running.Lock()
	running.emitters[e] = struct{}{}
	running.Unlock()
	if e.tick > 0 {
		e.loopDone = make(chan struct{})
		go e.loop()
	}
	return nil
}

// redactionKey returns the inherited HMAC key, or nil with the identity_join reason when it is missing or invalid.
func redactionKey() ([]byte, Capability) {
	text := os.Getenv("WANDB_X_PROVENANCE_REDACTION_KEY")
	if text == "" {
		return nil, Capability{Status: "partial", Reason: "missing_redaction_key"}
	}
	key, err := hex.DecodeString(text)
	if len(text) != 64 || err != nil || strings.ToLower(text) != text {
		return nil, Capability{Status: "partial", Reason: "invalid_redaction_key"}
	}
	return key, Capability{Status: "available"}
}

func (e *Emitter) loop() {
	defer close(e.loopDone)
	ticker := time.NewTicker(e.tick)
	defer ticker.Stop()
	for {
		e.flush()
		select {
		case <-ticker.C:
		case <-e.stop:
			return
		case <-e.done:
			return
		}
	}
}

type fieldShape int

const (
	quantityField fieldShape = iota + 1
	pseudonymField
	numberField
	textField
	ncclEnvField
)

var recordKinds = map[string]bool{
	"step":              true,
	"phase":             true,
	"metrics":           true,
	"lifecycle":         true,
	"checkpoint":        true,
	"binding":           true,
	"communication":     true,
	"diagnostic":        true,
	"capability":        true,
	"test_ground_truth": true,
	"quality":           true,
}

var capabilityStatuses = []string{
	"available",
	"partial",
	"unavailable",
	"permission_denied",
	"timeout",
	"unsupported",
	"self_disabled",
}

var payloadFields = func() map[string]fieldShape {
	fields := map[string]fieldShape{}
	for shape, keys := range map[fieldShape][]string{
		quantityField:  {"collector_cpu_ns", "peak_memory_bytes", "dropped_records", "queue_depth"},
		pseudonymField: {"gpu_uuid_hmac", "hostname_hmac", "instance_id_hmac", "pod_name_hmac", "node_name_hmac", "scheduler_uid_hmac", "topology_value_hmac"},
		numberField:    {"step", "duration_ms", "loss", "tokens", "cumulative_tokens", "tokens_per_second", "mfu_percent", "tflops", "flops", "finite_count", "nonfinite_count", "norm", "count", "timed_count", "lost_count", "bytes", "total_ms", "p50_ms", "p99_ms", "max_ms", "cuda_index", "rank", "local_rank", "node_rank", "attempt", "dp", "dp_shard", "dp_replicate", "tp", "pp", "cp", "ep", "world_size", "max_restarts"},
		textField:      {"phase", "event", "status", "reason", "source", "collective", "collector", "scenario", "transport", "configured", "loaded", "confidence"},
		ncclEnvField:   {"nccl_env"},
	} {
		for _, key := range keys {
			fields[key] = shape
		}
	}
	return fields
}()

// validField reports whether value has the shape payloadFields assigns to key in a record of kind.
func validField(kind, key string, value json.RawMessage) bool {
	switch payloadFields[key] {
	case quantityField:
		var number int64
		return kind == "quality" && json.Unmarshal(value, &number) == nil && number >= 0
	case pseudonymField:
		var pseudonym string
		prefix := strings.TrimSuffix(key, "_hmac") + "_"
		return json.Unmarshal(value, &pseudonym) == nil && strings.HasPrefix(pseudonym, prefix) &&
			len(pseudonym) == len(prefix)+24 &&
			strings.Trim(pseudonym[len(prefix):], "0123456789abcdef") == ""
	case numberField:
		var number float64
		return json.Unmarshal(value, &number) == nil && !bytes.Equal(value, []byte("null"))
	case textField:
		var name string
		return json.Unmarshal(value, &name) == nil && len(name) <= 128
	case ncclEnvField:
		var env map[string]string
		if kind != "capability" || json.Unmarshal(value, &env) != nil || len(env) > 32 {
			return false
		}
		for name, setting := range env {
			if !ncclEnvName.MatchString(name) || !ncclEnvValue.MatchString(setting) {
				return false
			}
		}
		return true
	}
	return false
}

// ncclEnvName and ncclEnvValue bound NCCL network evidence to allowlisted names and enum or numeric values.
var (
	ncclEnvName = regexp.MustCompile(
		`^NCCL_(NET|NET_PLUGIN|IB_DISABLE|GPUDIRECTTCPX_[A-Z_]{1,48}|FASTRAK_[A-Z_]{1,48})$`,
	)
	ncclEnvValue = regexp.MustCompile(`^(socket|ib|tcpx|tcpxo|efa|none|other|set|-?\d{1,10})$`)
)

// transportNames are the NCCL transport families Level 1 may report.
var transportNames = []string{"socket", "ib", "tcpx", "tcpxo", "efa"}

// capabilityRecord is the payload of a capability record.
type capabilityRecord struct {
	Collector  string            `json:"collector"`
	Status     string            `json:"status"`
	Reason     string            `json:"reason"`
	Source     string            `json:"source"`
	Transport  string            `json:"transport"`
	Configured string            `json:"configured"`
	Loaded     string            `json:"loaded"`
	Confidence string            `json:"confidence"`
	Env        map[string]string `json:"nccl_env"`
}

// payloadOf returns the decoded payload of a well-formed record, or false if core must reject it.
func (e *Emitter) payloadOf(record Record) (map[string]json.RawMessage, bool) {
	var payload map[string]json.RawMessage
	if len(record.PayloadJSON) > 64<<10 || record.MonotonicNS < e.lastMonotonic ||
		!recordKinds[record.Kind] ||
		json.Unmarshal(record.PayloadJSON, &payload) != nil ||
		payload == nil {
		return nil, false
	}
	for key, value := range payload {
		if !validField(record.Kind, key, value) {
			return nil, false
		}
	}
	if record.Kind == "capability" {
		var capability capabilityRecord
		_ = json.Unmarshal(record.PayloadJSON, &capability)
		_, exists := e.manifest.Capabilities[capability.Collector]
		if capability.Collector == "" || !slices.Contains(capabilityStatuses, capability.Status) ||
			(!exists && len(e.manifest.Capabilities) >= 64) {
			return nil, false
		}
	}
	if len(e.redactor.key) == 0 {
		for key := range payload {
			if payloadFields[key] != pseudonymField {
				continue
			}
			delete(payload, key)
			if record.Kind == "binding" && key == "gpu_uuid_hmac" {
				payload["status"] = json.RawMessage(`"partial"`)
				payload["reason"], _ = json.Marshal(e.manifest.Capabilities["identity_join"].Reason)
			}
		}
	}
	return payload, true
}

func (e *Emitter) AddRecord(record Record) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if !e.active || e.stopped || e.collectionDisabled {
		return
	}
	elapsed := collectorCPU()
	defer func() { e.addCollectorCPU(elapsed()) }()
	payload, ok := e.payloadOf(record)
	if !ok {
		e.quality.RejectedRecords++
		return
	}
	header := e.header(record.Kind)
	if record.WallTimeNS > 0 {
		header.CollectedAt = time.Unix(0, record.WallTimeNS).UTC()
	}
	encoded, _ := json.Marshal(header)
	var document map[string]json.RawMessage
	_ = json.Unmarshal(encoded, &document)
	for key, value := range payload {
		if key == "rank" || key == "attempt" {
			continue
		}
		document[key] = value
	}
	document["monotonic_ns"], _ = json.Marshal(record.MonotonicNS)
	encoded, err := json.Marshal(document)
	if err != nil {
		e.quality.RejectedRecords++
		return
	}
	if len(e.queue) >= queueCapacity || e.queuedBytes+len(encoded) > maxBufferedBytes {
		e.quality.DroppedRecords++
		if !e.backoff {
			e.backoff = true
			e.quality.BackoffTransitions++
			e.manifest.Capabilities["sampling"] = Capability{
				Status: "partial",
				Reason: "queue_pressure",
			}
		}
		return
	}
	e.observe(record, payload)
	e.lastMonotonic = record.MonotonicNS
	e.queue = append(e.queue, encoded)
	e.queuedBytes += len(encoded)
	e.quality.QueueDepth = len(e.queue)
	e.quality.PeakMemoryBytes = max(e.quality.PeakMemoryBytes, int64(e.queuedBytes+e.chunk.Len()))
}

// observe applies an accepted record's effects on the manifest and quality counters.
func (e *Emitter) observe(record Record, payload map[string]json.RawMessage) {
	switch record.Kind {
	case "binding":
		e.manifest.Binding = payload
		e.boundUUID = ""
		_ = json.Unmarshal(payload["gpu_uuid_hmac"], &e.boundUUID)
		e.gpuBound = e.boundUUID != ""
		e.manifest.Device = e.gpuDevices[e.boundUUID]
	case "capability":
		var capability capabilityRecord
		_ = json.Unmarshal(record.PayloadJSON, &capability)
		e.manifest.Capabilities[capability.Collector] = Capability{
			Status: capability.Status,
			Reason: capability.Reason,
		}
		if capability.Collector == "torchtitan" && capability.Status == "available" {
			e.manifest.Framework = "torchtitan"
			if len(capability.Source) >= 7 && len(capability.Source) <= 40 &&
				strings.Trim(capability.Source, "0123456789abcdef") == "" {
				e.manifest.FrameworkRevision = capability.Source
			}
		}
		if capability.Collector == "writer" && capability.Status == "self_disabled" {
			e.collectionDisabled = true
		}
		if capability.Collector == "nccl_transport" && e.config.Level == 1 &&
			slices.Contains(transportNames, capability.Transport) {
			e.transport = &platform.TransportEvidence{
				Name:       capability.Transport,
				Source:     "proc_maps+nccl_env",
				Confidence: capability.Confidence,
				Configured: capability.Configured,
				Loaded:     capability.Loaded,
				Env:        capability.Env,
			}
			if e.manifest.Platform != nil {
				e.manifest.Platform.Transport = *e.transport
			}
		}
	case "quality":
		var metrics struct {
			CPU   int64 `json:"collector_cpu_ns"`
			Peak  int64 `json:"peak_memory_bytes"`
			Drops int64 `json:"dropped_records"`
		}
		_ = json.Unmarshal(record.PayloadJSON, &metrics)
		cpu := max(0, metrics.CPU-e.pythonCPU)
		e.addCollectorCPU(&cpu)
		e.quality.DroppedRecords += max(0, metrics.Drops-e.pythonDrops)
		e.pythonCPU = max(e.pythonCPU, metrics.CPU)
		e.pythonDrops = max(e.pythonDrops, metrics.Drops)
		e.quality.PeakMemoryBytes = max(
			e.quality.PeakMemoryBytes,
			metrics.Peak+int64(e.queuedBytes+e.chunk.Len()),
		)
	}
	for _, axis := range []string{"dp_shard", "dp_replicate", "tp", "pp", "cp", "ep"} {
		var coordinate int
		if value, ok := payload[axis]; ok && json.Unmarshal(value, &coordinate) == nil &&
			coordinate >= 0 {
			if e.manifest.ParallelCoordinates == nil {
				e.manifest.ParallelCoordinates = map[string]int{}
			}
			e.manifest.ParallelCoordinates[axis] = coordinate
		}
	}
}

// addCollectorCPU adds ns to the collector CPU counter; nil means the thread clock is unavailable.
func (e *Emitter) addCollectorCPU(ns *int64) {
	if ns == nil {
		return
	}
	if e.quality.CollectorCPUNS == nil {
		e.quality.CollectorCPUNS = new(int64)
	}
	*e.quality.CollectorCPUNS += *ns
}

// OnSample records the latest accelerator stats and flushes; slow collection runs outside the lock.
func (e *Emitter) OnSample(stats *spb.StatsRecord, sampleErr error) {
	e.mu.Lock()
	if !e.active || e.stopped {
		e.mu.Unlock()
		return
	}
	if sampleErr != nil {
		e.quality.Gaps++
	}
	if stats != nil {
		e.latest = stats
	}
	e.mu.Unlock()
	e.flush()
}

func (e *Emitter) flush() {
	e.io.Lock()
	defer e.io.Unlock()
	elapsed := collectorCPU()
	e.mu.Lock()
	if !e.active || e.stopped {
		e.mu.Unlock()
		elapsed()
		return
	}
	now := e.now()
	e.flushQueue(now)
	interval := 15 * time.Second
	if e.backoff {
		interval = 60 * time.Second
	}
	due := !e.collectionDisabled && (e.lastSample.IsZero() || now.Sub(e.lastSample) >= interval)
	stats := e.latest
	if due {
		e.lastSample = now
		e.latest = nil
	}
	level := e.config.Level
	e.mu.Unlock()

	var host map[string]float64
	var scope string
	var snapshot *platform.Snapshot
	if due {
		host, scope = e.sampleHost()
		if e.platform != nil {
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			collected := e.platform.Collect(ctx, level)
			cancel()
			snapshot = &collected
		}
	}

	e.mu.Lock()
	if e.stopped {
		e.mu.Unlock()
		elapsed()
		return
	}
	if due {
		e.appendSample(now, stats, host, scope, snapshot)
	}
	e.chargeFlushCPU(elapsed(), due)
	if now.Sub(e.chunkStarted) >= 300*time.Second {
		e.seal(now)
	}
	// Chunks are written first so the documents carry their compression time.
	e.writeQueued()
	if now.Sub(e.lastDocuments) >= 60*time.Second {
		if e.documents(false) != nil {
			e.quality.Gaps++
		}
		e.writeQueued()
	}
	files := e.takeFiles()
	e.mu.Unlock()
	if files == nil {
		return
	}
	started := time.Now()
	accepted := e.emit(files)
	e.mu.Lock()
	defer e.mu.Unlock()
	e.quality.UploadRegistrationNS += time.Since(started).Nanoseconds()
	if accepted {
		return
	}
	for _, item := range files.Files {
		if len(e.pending) >= queueCapacity {
			e.manifest.Capabilities["upload_registration"] = Capability{
				Status: "self_disabled",
				Reason: "queue_pressure",
			}
			e.quality.DroppedRecords++
			continue
		}
		e.pending[item.Path] = item.Policy
	}
}

// chargeFlushCPU accounts a flush's CPU time and backs off sampling after three over-budget samples.
func (e *Emitter) chargeFlushCPU(duration *int64, sampled bool) {
	if duration == nil {
		e.manifest.Capabilities["collector_cpu"] = Capability{
			Status: "unsupported",
			Reason: "thread_clock_unavailable",
		}
		return
	}
	e.addCollectorCPU(duration)
	switch {
	case !sampled:
	case *duration > 75_000_000:
		e.pressureSamples++
	default:
		e.pressureSamples = 0
	}
	if e.pressureSamples >= 3 && !e.backoff {
		e.backoff = true
		e.quality.BackoffTransitions++
		e.manifest.Capabilities["sampling"] = Capability{Status: "partial", Reason: "cpu_budget"}
	}
}

func (e *Emitter) emit(files *spb.FilesRecord) bool {
	if e.work == nil {
		return true
	}
	record := &spb.Record{RecordType: &spb.Record_Files{Files: files}}
	return e.work.AddWorkOrCancel(e.done, runwork.NoRequest(runwork.WorkFromRecord(record)))
}

func (e *Emitter) appendSample(
	now time.Time,
	stats *spb.StatsRecord,
	host map[string]float64,
	scope string,
	snapshot *platform.Snapshot,
) {
	e.resolveGPUs()
	values := make(map[string]float64)
	dropped, joined := 0, false
	for _, item := range stats.GetItem() {
		if !strings.HasPrefix(item.Key, "gpu.") && !strings.HasPrefix(item.Key, "cpu") &&
			!strings.HasPrefix(item.Key, "memory") {
			continue
		}
		key := item.Key
		if strings.HasPrefix(key, "gpu.") {
			parts := strings.SplitN(key, ".", 3)
			if len(parts) != 3 || !e.gpuBound || e.gpuIDs[parts[1]] != e.boundUUID {
				dropped++
				continue
			}
			key = "gpu." + e.boundUUID + "." + parts[2]
			joined = true
		}
		var value float64
		if json.Unmarshal([]byte(item.ValueJson), &value) == nil && !math.IsNaN(value) &&
			!math.IsInf(value, 0) {
			values[key] = value
		}
	}
	// GPU samples that never join the bound device are a gap, not silence.
	if dropped > 0 && !joined {
		e.quality.Gaps++
	}
	if len(values) > 0 || len(host) > 0 {
		encoded, err := json.Marshal(struct {
			Header
			Values    map[string]float64 `json:"values,omitempty"`
			Host      map[string]float64 `json:"host,omitempty"`
			HostScope string             `json:"host_scope,omitempty"`
		}{e.header("infrastructure"), values, host, scope})
		if err == nil {
			e.appendRecord(encoded, now, "infrastructure")
		}
	}
	if snapshot != nil {
		if e.transport != nil {
			snapshot.Transport = *e.transport
		}
		e.manifest.Platform = snapshot
		encoded, err := json.Marshal(struct {
			Header
			Snapshot platform.Snapshot `json:"platform"`
		}{e.header("platform"), *snapshot})
		if err == nil {
			e.appendRecord(encoded, now, "platform")
		}
	}
}

// resolveGPUs pseudonymizes the probed GPUs once so stats indices map to device identities.
func (e *Emitter) resolveGPUs() {
	if len(e.gpuIDs) == 0 && e.environment != nil {
		for index, gpu := range e.environment.GpuNvidia {
			if id, ok := e.redactor.Pseudonym("gpu_uuid", gpu.Uuid); ok {
				e.gpuIDs[strconv.Itoa(index)] = id
				pci, _ := e.redactor.Pseudonym("pci", gpu.PciBusId)
				e.gpuDevices[id] = &Device{
					ID:          id,
					Name:        gpu.Name,
					MemoryBytes: gpu.MemoryTotal,
					PCIID:       pci,
					NUMA:        gpu.NumaNode,
				}
			}
		}
	}
	e.manifest.Device = e.gpuDevices[e.boundUUID]
}

func (e *Emitter) flushQueue(now time.Time) {
	for _, line := range e.queue {
		var record struct {
			Kind string `json:"kind"`
		}
		_ = json.Unmarshal(line, &record)
		e.appendRecord(line, now, record.Kind)
	}
	clear(e.queue)
	e.queue = e.queue[:0]
	e.queuedBytes = 0
	e.quality.QueueDepth = 0
}

func (e *Emitter) appendRecord(line []byte, now time.Time, kind string) {
	if e.chunk.Len()+len(line)+1 > maxBufferedBytes {
		e.seal(now)
	}
	e.chunk.Write(line)
	e.chunk.WriteByte('\n')
	e.quality.SerializedBytes += int64(len(line) + 1)
	e.quality.PeakMemoryBytes = max(e.quality.PeakMemoryBytes, int64(e.queuedBytes+e.chunk.Len()))
	e.records[kind]++
}

func (e *Emitter) documents(finalized bool) error {
	policy := spb.FilesItem_NOW
	if finalized {
		policy = spb.FilesItem_END
	}
	paths := Paths{WriterID: e.config.WriterID}
	e.manifest.Header = e.header("manifest")
	e.manifest.Quality = e.quality
	e.manifest.Finalized = finalized
	e.manifest.Exit = e.exit
	e.resolveGPUs()
	gpu := Capability{Status: "available"}
	switch {
	case e.environment == nil:
		gpu = Capability{Status: "unavailable", Reason: "environment_not_probed"}
	case len(e.environment.GpuNvidia) == 0:
		gpu = Capability{Status: "unavailable", Reason: "no_nvidia_gpu"}
	case len(e.redactor.key) == 0:
		gpu = Capability{
			Status: "unavailable",
			Reason: e.manifest.Capabilities["identity_join"].Reason,
		}
	case len(e.gpuIDs) == 0:
		gpu = Capability{Status: "unavailable", Reason: "gpu_identity_unavailable"}
	case !e.gpuBound:
		gpu = Capability{Status: "unavailable", Reason: "binding_not_proven"}
	case e.manifest.Device == nil:
		gpu = Capability{Status: "unavailable", Reason: "binding_not_joined"}
	}
	e.manifest.Capabilities["gpu_metrics"] = gpu
	e.manifest.PeakFLOPs, e.manifest.Capabilities["peak_flops"] = peakFLOPs(e.manifest.Device)
	if e.backoff {
		e.manifest.SamplingIntervalS = 60
	}
	if err := e.writeDocument(paths.Manifest(), e.manifest, policy); err != nil {
		return err
	}
	if err := e.writeDocument(
		paths.Rollup(),
		Rollup{
			Header:       e.header("rollup"),
			Quality:      e.quality,
			Records:      e.records,
			LastSequence: e.sequence - 1,
			Finalized:    finalized,
		},
		policy,
	); err != nil {
		return err
	}
	if e.config.Primary && (finalized || e.lastDocuments.IsZero()) {
		pointer := Primary{
			Version:   2,
			WriterID:  e.config.WriterID,
			Attempt:   e.config.Attempt,
			StartedAt: e.startedAt.UTC(),
			Manifest:  paths.Manifest(),
			Rollup:    paths.Rollup(),
			Finalized: finalized,
		}
		if err := e.writeDocument(paths.Primary(), pointer, policy); err != nil {
			return err
		}
		e.writes[len(e.writes)-1].primary = &pointer
	}
	e.lastDocuments = e.now()
	return nil
}

func (e *Emitter) takeFiles() *spb.FilesRecord {
	if len(e.pending) == 0 {
		return nil
	}
	result := &spb.FilesRecord{}
	names := make([]string, 0, len(e.pending))
	for name := range e.pending {
		names = append(names, name)
	}
	slices.Sort(names)
	for _, name := range names {
		result.Files = append(result.Files, &spb.FilesItem{Path: name, Policy: e.pending[name]})
	}
	clear(e.pending)
	return result
}

// Drain stops the loop, waits for in-flight flushes, writes the final files and returns those left to register.
func (e *Emitter) Drain() DrainResult {
	e.mu.Lock()
	if !e.active || e.stopped {
		defer e.mu.Unlock()
		return DrainResult{Quality: e.quality}
	}
	e.stopped = true
	close(e.stop)
	e.mu.Unlock()
	running.Lock()
	delete(running.emitters, e)
	running.Unlock()
	if e.loopDone != nil {
		<-e.loopDone
	}
	e.io.Lock()
	defer e.io.Unlock()
	e.mu.Lock()
	e.flushQueue(e.now())
	e.seal(e.now())
	e.writeQueued()
	if e.documents(true) != nil {
		e.quality.Gaps++
	}
	e.writeQueued()
	defer e.mu.Unlock()
	return DrainResult{Files: e.takeFiles(), Quality: e.quality}
}

func (e *Emitter) header(kind string) Header {
	result := Header{
		Version:     2,
		Kind:        kind,
		WriterID:    e.config.WriterID,
		CollectedAt: e.now().UTC(),
		Attempt:     e.config.Attempt,
		Rank:        e.config.Rank,
		Source:      "wandb-core",
	}
	if e.runtime != nil {
		if runtime, ok := e.runtime(); ok {
			seconds := runtime.Seconds()
			result.RuntimeS = &seconds
		}
	}
	return result
}

func (e *Emitter) sampleHost() (map[string]float64, string) {
	host := make(map[string]float64)
	scope := ""
	if e.host.ProcRoot == "" {
		return host, scope
	}
	e.sampleSchedStats(host)
	e.sampleCgroupCPU(host)
	if e.host.CgroupDir != "" {
		if data, err := os.ReadFile(filepath.Join(e.host.CgroupDir, "memory.current")); err == nil {
			if value, err := strconv.ParseUint(
				strings.TrimSpace(string(data)),
				10,
				64,
			); err == nil {
				host["cgroup_memory.current_bytes"] = float64(value)
			}
		}
		if data, err := os.ReadFile(filepath.Join(e.host.CgroupDir, "io.stat")); err == nil {
			for line := range strings.SplitSeq(string(data), "\n") {
				for _, field := range strings.Fields(line) {
					key, raw, ok := strings.Cut(field, "=")
					if !ok ||
						!slices.Contains(
							[]string{"rbytes", "wbytes", "rios", "wios", "dbytes", "dios"},
							key,
						) {
						continue
					}
					if value, err := strconv.ParseUint(raw, 10, 64); err == nil {
						host["cgroup_io."+key] += float64(value)
					}
				}
			}
		}
	}

	switch {
	case e.host.CgroupDir != "" && readPressure(func(res string) string {
		return filepath.Join(e.host.CgroupDir, res+".pressure")
	}, host):
		scope = "cgroup"
	case readPressure(func(res string) string {
		return filepath.Join(e.host.ProcRoot, "pressure", res)
	}, host):
		scope = "host"
	}
	return host, scope
}

// sampleSchedStats walks the writer's process/thread tree and adds aggregate schedstat counters into host.
func (e *Emitter) sampleSchedStats(host map[string]float64) {
	var run, wait, timeslices uint64
	threads, processes := 0, 0
	seen := make(map[int]bool)
	for stack := []int{e.host.Pid}; len(stack) > 0 && len(seen) < 4096; {
		pid := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if seen[pid] {
			continue
		}
		seen[pid] = true
		if e.host.ExcludePid != 0 && pid == e.host.ExcludePid {
			continue
		}
		taskDir := filepath.Join(e.host.ProcRoot, strconv.Itoa(pid), "task")
		tasks, _ := os.ReadDir(taskDir)
		if len(tasks) > 0 {
			processes++
		}
		for _, task := range tasks[:min(len(tasks), 8192)] {
			dir := filepath.Join(taskDir, task.Name())
			if b, err := os.ReadFile(filepath.Join(dir, "schedstat")); err == nil {
				var r, w, s uint64
				if _, err := fmt.Sscan(string(b), &r, &w, &s); err == nil {
					run, wait, timeslices = run+r, wait+w, timeslices+s
					threads++
				}
			}
			// Each thread lists only the children it spawned.
			if b, err := os.ReadFile(filepath.Join(dir, "children")); err == nil {
				for _, f := range strings.Fields(string(b)) {
					if c, err := strconv.Atoi(f); err == nil {
						stack = append(stack, c)
					}
				}
			}
		}
	}
	if threads > 0 {
		host["sched.run_ns"] = float64(run)
		host["sched.wait_ns"] = float64(wait)
		host["sched.timeslices"] = float64(timeslices)
		host["sched.threads"] = float64(threads)
		host["sched.processes"] = float64(processes)
	}
}

// sampleCgroupCPU adds the writer's cgroup cpu.stat counters into host.
func (e *Emitter) sampleCgroupCPU(host map[string]float64) {
	if e.host.CgroupDir == "" {
		return
	}
	b, err := os.ReadFile(filepath.Join(e.host.CgroupDir, "cpu.stat"))
	if err != nil {
		return
	}
	for line := range strings.SplitSeq(string(b), "\n") {
		if k, v, ok := strings.Cut(line, " "); ok {
			if n, err := strconv.ParseUint(strings.TrimSpace(v), 10, 64); err == nil {
				host["cgroup_cpu."+k] = float64(n)
			}
		}
	}
}
