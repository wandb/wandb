// Package provenance writes rank-to-GPU provenance and packed GPU/host telemetry as run log lines.
package provenance

import (
	"encoding/json"
	"fmt"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/version"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// LinePrefix marks provenance lines in the run's logs.
const LinePrefix = "[wandb.telemetry] "

// maxEnvValueLen bounds each raw value copied into a rank line.
const maxEnvValueLen = 256

// defaultMaxLineBytes stays well under the backend's 100 KB console line truncation.
const defaultMaxLineBytes = 32 << 10

const (
	SourceNVMLProcess        = "nvml_process"
	SourceCudaRuntime        = "cuda_runtime"
	SourceCVDUUID            = "cuda_visible_devices_uuid"
	SourceUnresolved         = "unresolved"
	SourceConflict           = "conflict"
	SourceNoNvidiaGPU        = "no_nvidia_gpu"
	SourceGPUInfoUnavailable = "gpu_info_unavailable"
)

// Job identifies the scheduler job a writer belongs to.
type Job struct {
	Scheduler     string `json:"scheduler"`
	Cluster       string `json:"cluster,omitempty"`
	ID            string `json:"id,omitempty"`
	StepID        string `json:"step_id,omitempty"`
	Attempt       *int   `json:"attempt,omitempty"`
	StartTime     string `json:"start_time,omitempty"`
	Nodelist      string `json:"nodelist,omitempty"`
	NumNodes      *int   `json:"num_nodes,omitempty"`
	WorldSize     *int   `json:"world_size,omitempty"`
	NtasksPerNode string `json:"ntasks_per_node,omitempty"`
	GpusOnNode    *int   `json:"gpus_on_node,omitempty"`
	TopologyAddr  string `json:"topology_addr,omitempty"`
}

// Rank identifies a writer within its job.
type Rank struct {
	Global   *int   `json:"global,omitempty"`
	Local    *int   `json:"local,omitempty"`
	Node     *int   `json:"node,omitempty"`
	Hostname string `json:"hostname,omitempty"`
}

// Launch is what the launcher environment says about a writer.
type Launch struct {
	Job  Job
	Rank Rank
	Env  map[string]string
}

var launcherEnvKeys = []string{
	"MASTER_ADDR", "MASTER_PORT", "TORCHELASTIC_RUN_ID",
	"LOCAL_WORLD_SIZE", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER",
}

// ReadLaunch reads Slurm, torchelastic and OpenMPI variables from env.
func ReadLaunch(env map[string]string, hostname string) Launch {
	has := func(k string) bool { _, ok := env[k]; return ok }
	capped := func(v string) string { return v[:min(len(v), maxEnvValueLen)] }

	id, ok := env["SLURM_JOB_ID"]
	if !ok {
		id = env["TORCHELASTIC_RUN_ID"]
	}

	l := Launch{
		Job: Job{
			Scheduler:     "none",
			Cluster:       env["SLURM_CLUSTER_NAME"],
			ID:            id,
			StepID:        env["SLURM_STEP_ID"],
			Attempt:       firstInt(env, "SLURM_RESTART_COUNT", "TORCHELASTIC_RESTART_COUNT"),
			StartTime:     env["SLURM_JOB_START_TIME"],
			Nodelist:      capped(env["SLURM_JOB_NODELIST"]),
			NumNodes:      firstInt(env, "SLURM_JOB_NUM_NODES"),
			WorldSize:     firstInt(env, "WORLD_SIZE", "SLURM_NTASKS", "OMPI_COMM_WORLD_SIZE"),
			NtasksPerNode: env["SLURM_NTASKS_PER_NODE"],
			GpusOnNode:    firstInt(env, "SLURM_GPUS_ON_NODE"),
			TopologyAddr:  env["SLURM_TOPOLOGY_ADDR"],
		},
		Rank: Rank{
			Global:   firstInt(env, "RANK", "SLURM_PROCID", "OMPI_COMM_WORLD_RANK", "PMIX_RANK"),
			Local:    firstInt(env, "LOCAL_RANK", "SLURM_LOCALID", "OMPI_COMM_WORLD_LOCAL_RANK"),
			Node:     firstInt(env, "GROUP_RANK", "SLURM_NODEID"),
			Hostname: hostname,
		},
	}

	switch {
	case has("SLURM_JOB_ID"):
		l.Job.Scheduler = "slurm"
	case has("TORCHELASTIC_RUN_ID") || (has("LOCAL_RANK") && has("WORLD_SIZE")):
		l.Job.Scheduler = "torchelastic"
	case has("OMPI_COMM_WORLD_RANK") || has("PMIX_RANK"):
		l.Job.Scheduler = "openmpi"
	}

	for _, k := range launcherEnvKeys {
		v, ok := env[k]
		if !ok {
			continue
		}
		if l.Env == nil {
			l.Env = make(map[string]string)
		}
		l.Env[k] = capped(v)
	}

	return l
}

// firstInt parses the first present key; a malformed value yields nil, never 0.
func firstInt(env map[string]string, keys ...string) *int {
	for _, k := range keys {
		v, ok := env[k]
		if !ok {
			continue
		}
		n, err := strconv.Atoi(strings.TrimSpace(v))
		if err != nil {
			return nil
		}
		return &n
	}
	return nil
}

// GpuIdentity is a physical GPU as seen by NVML.
type GpuIdentity struct {
	UUID      string `json:"uuid"`
	PciBusID  string `json:"pci_bus_id,omitempty"`
	Serial    string `json:"serial,omitempty"`
	IndexHost *int   `json:"index_host,omitempty"`
	NumaNode  *int   `json:"numa_node,omitempty"`
	LocalCPUs string `json:"local_cpulist,omitempty"`
}

// Binding is which GPUs a writer is bound to and the evidence for it.
type Binding struct {
	Source          string        `json:"binding_source"`
	GPUs            []GpuIdentity `json:"gpus"`
	Ambiguous       bool          `json:"ambiguous,omitempty"`
	GPUsNVML        []GpuIdentity `json:"gpus_nvml,omitempty"`
	GPUsCudaRuntime []GpuIdentity `json:"gpus_cuda_runtime,omitempty"`
}

// ResolveBinding picks the writer's GPUs from the strongest available evidence.
func ResolveBinding(
	metrics *spb.StatsRecord,
	gpus []GpuIdentity,
	reported *spb.DeviceBindingRecord,
	env map[string]string,
) Binding {
	seen := make(map[int]bool)
	for _, item := range metrics.GetItem() {
		rest, ok := strings.CutPrefix(item.GetKey(), "gpu.process.")
		if !ok {
			continue
		}
		idx, _, _ := strings.Cut(rest, ".")
		if i, err := strconv.Atoi(idx); err == nil && i >= 0 && i < len(gpus) {
			seen[i] = true
		}
	}
	var nvml []GpuIdentity
	for _, i := range slices.Sorted(maps.Keys(seen)) {
		nvml = append(nvml, gpus[i])
	}

	if u := reported.GetUuid(); u != "" {
		sameUUID := func(g GpuIdentity) bool { return strings.EqualFold(g.UUID, u) }
		cuda := GpuIdentity{UUID: u}
		if i := slices.IndexFunc(gpus, sameUUID); i >= 0 {
			cuda = gpus[i]
		}
		switch {
		case len(nvml) == 0:
			return Binding{Source: SourceCudaRuntime, GPUs: []GpuIdentity{cuda}}
		case slices.ContainsFunc(nvml, sameUUID):
			return Binding{Source: SourceNVMLProcess, GPUs: []GpuIdentity{cuda}}
		default:
			return Binding{
				Source:          SourceConflict,
				GPUs:            []GpuIdentity{},
				GPUsNVML:        nvml,
				GPUsCudaRuntime: []GpuIdentity{cuda},
			}
		}
	}

	if len(nvml) > 0 {
		return Binding{Source: SourceNVMLProcess, GPUs: nvml, Ambiguous: len(nvml) > 1}
	}

	// Integer entries use CUDA ordering, which need not match NVML's.
	if cvd := strings.Split(env["CUDA_VISIBLE_DEVICES"], ","); len(cvd) == 1 &&
		strings.HasPrefix(cvd[0], "GPU-") {
		for _, g := range gpus {
			if strings.EqualFold(g.UUID, cvd[0]) {
				return Binding{Source: SourceCVDUUID, GPUs: []GpuIdentity{g}}
			}
		}
	}

	return Binding{Source: SourceUnresolved, GPUs: []GpuIdentity{}}
}

// sampleFields maps xpu metric names to sample keys, in output order.
var sampleFields = []struct{ xpu, name string }{
	{"smActive", "sm_active"},
	{"pipeTensorActive", "tensor_active"},
	{"smOccupancy", "sm_occupancy"},
	{"dramActive", "dram_active"},
	{"smClock", "sm_clock_mhz"},
	{"memoryClock", "mem_clock_mhz"},
	{"powerWatts", "power_w"},
	{"temp", "temp_c"},
	{"gpu", "util_pct"},
	{"memory", "mem_util_pct"},
	{"nvlinkTxBytes", "nvlink_tx_bps"},
	{"nvlinkRxBytes", "nvlink_rx_bps"},
	{"clockThrottleReasons", "throttle_reasons"},
}

type header struct {
	V           int      `json:"v"`
	Kind        string   `json:"kind"`
	CollectedAt string   `json:"collected_at"`
	SDK         string   `json:"sdk"`
	WriterID    string   `json:"writer_id"`
	RuntimeS    *float64 `json:"runtime_s,omitempty"`
	Step        *float64 `json:"step,omitempty"`
	StepKey     string   `json:"step_key,omitempty"`
}

type stepValue struct {
	key   string
	value float64
}

type rankBlock struct {
	Rank
	Binding
	CPUsAllowed string `json:"cpus_allowed,omitempty"`
	CPUAffinity string `json:"cpu_affinity,omitempty"`
}

type rankRecord struct {
	header
	Job         Job               `json:"job"`
	Rank        rankBlock         `json:"rank"`
	Cgroup      string            `json:"cgroup,omitempty"`
	LauncherEnv map[string]string `json:"launcher_env,omitempty"`
}

type windowTicks struct {
	DtMs     []int64    `json:"dt_ms"`
	RuntimeS []*float64 `json:"runtime_s"`
	Step     []*float64 `json:"step"`
}

type windowRecord struct {
	header
	Rank          *int                                    `json:"rank,omitempty"`
	T0            string                                  `json:"t0"`
	Ticks         windowTicks                             `json:"ticks"`
	GPUs          map[string]map[string][]json.RawMessage `json:"gpus,omitempty"`
	Host          map[string][]*float64                   `json:"host,omitempty"`
	PressureScope string                                  `json:"pressure_scope,omitempty"`
	Gaps          []int                                   `json:"gaps,omitempty"`
}

// EmitterParams configures an Emitter.
type EmitterParams struct {
	Launch   Launch
	WriterID string

	// Emit writes one log line.
	Emit func(line string)

	// Probe returns NVML GPU identities; called once, on the first sample.
	Probe func() *spb.EnvironmentRecord

	// Runtime returns the run's `_runtime`; false before the run is initialized.
	Runtime func() (time.Duration, bool)

	Host HostPaths

	// FlushInterval is how long ticks are packed into one window line; <= 0 flushes every tick.
	FlushInterval time.Duration

	// MaxLineBytes flushes a window early once its line reaches this size; 0 means the default.
	MaxLineBytes int

	Now func() time.Time
}

// Emitter turns XPU samples and host counters into provenance log lines.
type Emitter struct {
	mu sync.Mutex

	launch       Launch
	writerID     string
	emit         func(string)
	probe        func() *spb.EnvironmentRecord
	runtime      func() (time.Duration, bool)
	host         HostPaths
	flushEvery   time.Duration
	maxLineBytes int
	now          func() time.Time

	// reported and step are lock-free because the handler goroutine writes them.
	reported atomic.Pointer[spb.DeviceBindingRecord]
	step     atomic.Pointer[stepValue]

	initialized bool
	gpus        []GpuIdentity
	last        *Binding
	lastKey     string
	win         *windowRecord
	winStart    time.Time
}

func NewEmitter(p *EmitterParams) *Emitter {
	now := p.Now
	if now == nil {
		now = time.Now
	}
	runtime := p.Runtime
	if runtime == nil {
		runtime = func() (time.Duration, bool) { return 0, false }
	}
	maxLineBytes := p.MaxLineBytes
	if maxLineBytes <= 0 {
		maxLineBytes = defaultMaxLineBytes
	}
	return &Emitter{
		launch:       p.Launch,
		writerID:     p.WriterID,
		emit:         p.Emit,
		probe:        p.Probe,
		runtime:      runtime,
		host:         p.Host,
		flushEvery:   p.FlushInterval,
		maxLineBytes: maxLineBytes,
		now:          now,
	}
}

// SetDeviceBinding records the device the writer process reported; used from the next sample.
func (e *Emitter) SetDeviceBinding(r *spb.DeviceBindingRecord) {
	e.reported.Store(r)
}

// SetStep records the writer's latest step under the history key it came from.
func (e *Emitter) SetStep(key string, value float64) {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return
	}
	e.step.Store(&stepValue{key: key, value: value})
}

// OnSample handles one XPU sample tick; metrics is nil when sampling failed.
func (e *Emitter) OnSample(metrics *spb.StatsRecord, _ error) {
	e.mu.Lock()
	defer e.mu.Unlock()

	if !e.initialized {
		e.loadGPUIdentities()
	}

	now := e.now()
	host, scope := e.sampleHost()

	// XPU.Sample returns (nil, nil) both on a start failure and when there is nothing to sample.
	gap := len(e.gpus) > 0 && len(metrics.GetItem()) == 0
	gpus := make(map[string]map[string]json.RawMessage)
	if !gap && len(e.gpus) > 0 {
		e.emitRankIfChanged(metrics)
		gpus = e.boundGPUValues(metrics)
	}

	if !gap && len(gpus) == 0 && len(host) == 0 {
		return
	}

	e.appendTick(now, host, gpus, scope, gap)
}

// loadGPUIdentities probes NVML once and enriches each GPU with its NUMA node and local CPUs from sysfs.
func (e *Emitter) loadGPUIdentities() {
	e.initialized = true
	env := e.probe()
	for i, g := range env.GetGpuNvidia() {
		id := GpuIdentity{
			UUID:      g.GetUuid(),
			PciBusID:  g.GetPciBusId(),
			Serial:    g.GetSerial(),
			IndexHost: &i,
		}
		// sysfs uses a 4-digit lowercase domain: 00000000:1B:00.0 -> 0000:1b:00.0.
		if dom, rest, ok := strings.Cut(id.PciBusID, ":"); ok && e.host.SysRoot != "" {
			if d, err := strconv.ParseUint(dom, 16, 32); err == nil {
				dev := filepath.Join(e.host.SysRoot, "bus", "pci", "devices",
					fmt.Sprintf("%04x:%s", d, strings.ToLower(rest)))
				if b, err := os.ReadFile(filepath.Join(dev, "numa_node")); err == nil {
					if n, err := strconv.Atoi(
						strings.TrimSpace(string(b)),
					); err == nil &&
						n >= 0 {
						id.NumaNode = &n
					}
				}
				if b, err := os.ReadFile(filepath.Join(dev, "local_cpulist")); err == nil {
					id.LocalCPUs = strings.TrimSpace(string(b))
				}
			}
		}
		e.gpus = append(e.gpus, id)
	}
	if len(e.gpus) == 0 {
		source := SourceNoNvidiaGPU
		if env == nil {
			source = SourceGPUInfoUnavailable
		}
		if b, err := json.Marshal(rankRecord{
			header: e.header("rank"),
			Job:    e.launch.Job,
			Rank: rankBlock{
				Rank:    e.launch.Rank,
				Binding: Binding{Source: source, GPUs: []GpuIdentity{}},
			},
			Cgroup:      e.host.CgroupDir,
			LauncherEnv: e.launch.Env,
		}); err == nil {
			e.emit(LinePrefix + string(b))
		}
	}
}

// sampleHost reads scheduler, cgroup and PSI pressure counters for the writer's process tree.
func (e *Emitter) sampleHost() (map[string]float64, string) {
	host := make(map[string]float64)
	scope := ""
	if e.host.ProcRoot == "" {
		return host, scope
	}
	e.sampleSchedStats(host)
	e.sampleCgroupCPU(host)

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
	for stack := []int{e.host.Pid}; len(stack) > 0; {
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
		for _, task := range tasks {
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

// emitRankIfChanged resolves the writer's current GPU binding and emits a rank record when it changed.
func (e *Emitter) emitRankIfChanged(metrics *spb.StatsRecord) {
	b := ResolveBinding(metrics, e.gpus, e.reported.Load(), e.launch.Env)
	// Dedupe on the GPU set and conflict state, not binding_source, so a transient NVML miss doesn't re-emit.
	uuids := make([]string, len(b.GPUs))
	for i, g := range b.GPUs {
		uuids[i] = strings.ToUpper(g.UUID)
	}
	slices.Sort(uuids)
	key := strconv.FormatBool(b.Source == SourceConflict) + "|" + strings.Join(uuids, ",")
	if e.last != nil && (b.Source == SourceUnresolved || key == e.lastKey) {
		return
	}
	e.last, e.lastKey = &b, key
	block := rankBlock{Rank: e.launch.Rank, Binding: b}
	if e.host.ProcRoot != "" {
		status, _ := os.ReadFile(
			filepath.Join(e.host.ProcRoot, strconv.Itoa(e.host.Pid), "status"),
		)
		var cpusAllowedFull string
		for line := range strings.SplitSeq(string(status), "\n") {
			if v, ok := strings.CutPrefix(line, "Cpus_allowed_list:"); ok {
				cpusAllowedFull = strings.TrimSpace(v)
				block.CPUsAllowed = cpusAllowedFull[:min(len(cpusAllowedFull), maxEnvValueLen)]
			}
		}
		online, _ := os.ReadFile(
			filepath.Join(e.host.SysRoot, "devices", "system", "cpu", "online"),
		)
		allowed, onlineSet := parseCPUList(cpusAllowedFull), parseCPUList(string(online))
		local := make(map[int]bool)
		for _, g := range b.GPUs {
			maps.Copy(local, parseCPUList(g.LocalCPUs))
		}
		inLocal := 0
		for c := range allowed {
			if local[c] {
				inLocal++
			}
		}
		switch {
		case len(allowed) == 0 || len(local) == 0:
		case maps.Equal(allowed, onlineSet):
			block.CPUAffinity = "unbound"
		case inLocal == len(allowed):
			block.CPUAffinity = "local"
		case inLocal > 0:
			block.CPUAffinity = "partial"
		default:
			block.CPUAffinity = "remote"
		}
	}
	if b, err := json.Marshal(rankRecord{
		header:      e.header("rank"),
		Job:         e.launch.Job,
		Rank:        block,
		Cgroup:      e.host.CgroupDir,
		LauncherEnv: e.launch.Env,
	}); err == nil {
		e.emit(LinePrefix + string(b))
	}
}

// boundGPUValues extracts this tick's per-GPU sample fields for the GPUs in the current binding.
func (e *Emitter) boundGPUValues(metrics *spb.StatsRecord) map[string]map[string]json.RawMessage {
	gpus := make(map[string]map[string]json.RawMessage)
	values := make(map[string]string, len(metrics.GetItem()))
	for _, item := range metrics.GetItem() {
		values[item.GetKey()] = item.GetValueJson()
	}
	for _, g := range e.last.GPUs {
		if g.IndexHost == nil {
			continue
		}
		prefix := "gpu." + strconv.Itoa(*g.IndexHost) + "."
		m := make(map[string]json.RawMessage)
		for _, f := range sampleFields {
			if v, ok := values[prefix+f.xpu]; ok && json.Valid([]byte(v)) {
				m[f.name] = json.RawMessage(v)
			}
		}
		gpus[g.UUID] = m
	}
	return gpus
}

// appendTick appends the tick's host and GPU samples to the buffered window and flushes it if due.
func (e *Emitter) appendTick(
	now time.Time,
	host map[string]float64,
	gpus map[string]map[string]json.RawMessage,
	scope string,
	gap bool,
) {
	if e.win == nil {
		e.win = &windowRecord{T0: now.UTC().Format(time.RFC3339Nano)}
		e.winStart = now
	}
	w := e.win
	i := len(w.Ticks.DtMs)
	w.Ticks.DtMs = append(w.Ticks.DtMs, now.Sub(e.winStart).Milliseconds())
	var rt, step *float64
	if d, ok := e.runtime(); ok {
		secs := d.Seconds()
		rt = &secs
	}
	if st := e.step.Load(); st != nil {
		v := st.value
		step = &v
	}
	w.Ticks.RuntimeS = append(w.Ticks.RuntimeS, rt)
	w.Ticks.Step = append(w.Ticks.Step, step)
	if gap {
		w.Gaps = append(w.Gaps, i)
	}
	for uuid, m := range gpus {
		if w.GPUs == nil {
			w.GPUs = make(map[string]map[string][]json.RawMessage)
		}
		cols := w.GPUs[uuid]
		if cols == nil {
			cols = make(map[string][]json.RawMessage)
			w.GPUs[uuid] = cols
		}
		for name, v := range m {
			cols[name] = appendAt(cols[name], i, v)
		}
	}
	for k, v := range host {
		if w.Host == nil {
			w.Host = make(map[string][]*float64)
		}
		w.Host[k] = appendAt(w.Host[k], i, &v)
	}
	if scope != "" {
		w.PressureScope = scope
	}

	line, ok := e.windowLine()
	if !ok {
		e.win = nil
		return
	}
	if now.Sub(e.winStart) >= e.flushEvery || len(line) >= e.maxLineBytes {
		e.emit(line)
		e.win = nil
	}
}

// Drain returns the buffered window as a final line; call only once sampling has stopped.
func (e *Emitter) Drain() (string, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()

	if e.win == nil {
		return "", false
	}
	line, ok := e.windowLine()
	e.win = nil
	return line, ok
}

// windowLine pads every column to the tick count and renders the buffered window.
func (e *Emitter) windowLine() (string, bool) {
	w := e.win
	n := len(w.Ticks.DtMs)
	for _, cols := range w.GPUs {
		for k, col := range cols {
			cols[k] = padTo(col, n)
		}
	}
	for k, col := range w.Host {
		w.Host[k] = padTo(col, n)
	}
	w.header = e.header("window")
	w.Rank = e.launch.Rank.Global

	b, err := json.Marshal(w)
	if err != nil {
		return "", false
	}
	return LinePrefix + string(b), true
}

// appendAt appends v at index i, padding skipped ticks with the zero value (JSON null).
func appendAt[T any](col []T, i int, v T) []T {
	return append(padTo(col, i), v)
}

func padTo[T any](col []T, n int) []T {
	for len(col) < n {
		var zero T
		col = append(col, zero)
	}
	return col
}

func (e *Emitter) header(kind string) header {
	h := header{
		V:           1,
		Kind:        kind,
		CollectedAt: e.now().UTC().Format(time.RFC3339Nano),
		SDK:         version.Version,
		WriterID:    e.writerID,
	}
	if rt, ok := e.runtime(); ok {
		secs := rt.Seconds()
		h.RuntimeS = &secs
	}
	if st := e.step.Load(); st != nil {
		h.Step, h.StepKey = &st.value, st.key
	}
	return h
}
