package provenance_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o755))
	require.NoError(t, os.WriteFile(path, []byte(content), 0o644))
}

func hostEnv() *spb.EnvironmentRecord {
	return &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{
		{Uuid: "GPU-aaa", PciBusId: "00000000:1B:00.0"},
	}}
}

// fakeHost builds /proc, /sys and a cgroup dir for rank pid 100 with child process 200.
func fakeHost(t *testing.T, cpusAllowed string, withCgroup bool) provenance.HostPaths {
	t.Helper()
	root := t.TempDir()
	proc, sys, cg := filepath.Join(
		root,
		"proc",
	), filepath.Join(
		root,
		"sys",
	), filepath.Join(
		root,
		"cgroup",
	)
	writeFile(t, filepath.Join(proc, "100", "task", "100", "schedstat"), "1000 200 5\n")
	writeFile(t, filepath.Join(proc, "100", "task", "100", "children"), "200 ")
	writeFile(t, filepath.Join(proc, "100", "task", "101", "schedstat"), "10 20 1\n")
	writeFile(t, filepath.Join(proc, "200", "task", "200", "schedstat"), "5 5 1\n")
	writeFile(
		t,
		filepath.Join(proc, "100", "status"),
		"Name:\tpython\nCpus_allowed_list:\t"+cpusAllowed+"\n",
	)
	writeFile(
		t,
		filepath.Join(proc, "pressure", "cpu"),
		"some avg10=9.00 avg60=0.00 avg300=0.00 total=999\n",
	)
	writeFile(t, filepath.Join(sys, "devices", "system", "cpu", "online"), "0-7\n")
	writeFile(t, filepath.Join(sys, "bus", "pci", "devices", "0000:1b:00.0", "numa_node"), "0\n")
	writeFile(
		t,
		filepath.Join(sys, "bus", "pci", "devices", "0000:1b:00.0", "local_cpulist"),
		"0-3\n",
	)

	p := provenance.HostPaths{ProcRoot: proc, SysRoot: sys, Pid: 100}
	if withCgroup {
		writeFile(
			t,
			filepath.Join(cg, "cpu.stat"),
			"usage_usec 5000\nnr_throttled 3\nthrottled_usec 1200\n",
		)
		writeFile(
			t,
			filepath.Join(cg, "cpu.pressure"),
			"some avg10=1.50 avg60=0.00 avg300=0.00 total=42\nfull avg10=0.50 avg60=0.00 avg300=0.00 total=7\n",
		)
		writeFile(
			t,
			filepath.Join(cg, "memory.pressure"),
			"some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
		)
		p.CgroupDir = cg
	}
	return p
}

func TestEmitter_HostValuesInWindow(t *testing.T) {
	h := newHarness(hostEnv(), rank17, withHost(fakeHost(t, "0-3", true)))

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	host := recs[1]["host"].(map[string]any)
	assert.Equal(t, []any{1015.0}, host["sched.run_ns"])
	assert.Equal(t, []any{225.0}, host["sched.wait_ns"])
	assert.Equal(t, []any{7.0}, host["sched.timeslices"])
	assert.Equal(t, []any{3.0}, host["sched.threads"])
	assert.Equal(t, []any{2.0}, host["sched.processes"])
	assert.Equal(t, []any{3.0}, host["cgroup_cpu.nr_throttled"])
	assert.Equal(t, []any{42.0}, host["pressure.cpu.some_total_us"])
	assert.Equal(t, []any{1.5}, host["pressure.cpu.some_avg10"])
	assert.Equal(t, []any{7.0}, host["pressure.cpu.full_total_us"])
	assert.Contains(t, host, "pressure.memory.some_total_us")
	assert.NotContains(t, host, "pressure.io.some_total_us")
	assert.Equal(t, "cgroup", recs[1]["pressure_scope"])

	rank := recs[0]["rank"].(map[string]any)
	assert.Equal(t, "0-3", rank["cpus_allowed"])
	assert.Equal(t, "local", rank["cpu_affinity"])
	gpu := rank["gpus"].([]any)[0].(map[string]any)
	assert.EqualValues(t, 0, gpu["numa_node"])
	assert.Equal(t, "0-3", gpu["local_cpulist"])
}

func TestEmitter_HostValues_ExcludesOwnSubtree(t *testing.T) {
	hp := fakeHost(t, "0-3", true)
	hp.ExcludePid = 200
	h := newHarness(hostEnv(), rank17, withHost(hp))

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	host := recs[1]["host"].(map[string]any)
	assert.Equal(t, []any{1010.0}, host["sched.run_ns"])
	assert.Equal(t, []any{220.0}, host["sched.wait_ns"])
	assert.Equal(t, []any{6.0}, host["sched.timeslices"])
	assert.Equal(t, []any{2.0}, host["sched.threads"])
	assert.Equal(t, []any{1.0}, host["sched.processes"])
}

func TestEmitter_HostPressureFallsBackToHostScope(t *testing.T) {
	h := newHarness(hostEnv(), rank17, withHost(fakeHost(t, "0-3", false)))

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	w := h.decoded(t)[1]
	assert.Equal(t, "host", w["pressure_scope"])
	host := w["host"].(map[string]any)
	assert.Equal(t, []any{999.0}, host["pressure.cpu.some_total_us"])
	for k := range host {
		assert.False(t, strings.HasPrefix(k, "cgroup_cpu."), k)
	}
}

func TestEmitter_HostValuesDuringXPUGap(t *testing.T) {
	h := newHarness(hostEnv(), rank17, withHost(fakeHost(t, "0-3", true)))

	h.em.OnSample(nil, assert.AnError)

	recs := h.decoded(t)
	require.Equal(t, []string{"window"}, kinds(recs))
	assert.Equal(t, []any{0.0}, recs[0]["gaps"])
	assert.Contains(t, recs[0]["host"], "sched.run_ns")
}

func TestEmitter_NoHostDataNoHostBlock(t *testing.T) {
	h := newHarness(hostEnv(), rank17,
		withHost(provenance.HostPaths{ProcRoot: t.TempDir(), SysRoot: t.TempDir(), Pid: 1}))

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.NotContains(t, recs[1], "host")
	assert.NotContains(t, recs[0]["rank"].(map[string]any), "cpu_affinity")
}

func TestReadPressure_RejectsNonFinite(t *testing.T) {
	root := t.TempDir()
	proc := filepath.Join(root, "proc")
	writeFile(t, filepath.Join(proc, "pressure", "cpu"),
		"some avg10=NaN avg60=0.00 avg300=0.00 total=999\n")
	h := newHarness(hostEnv(), rank17,
		withHost(provenance.HostPaths{ProcRoot: proc, SysRoot: t.TempDir(), Pid: 1}))

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	host := recs[1]["host"].(map[string]any)
	assert.NotContains(t, host, "pressure.cpu.some_avg10")
	assert.Equal(t, []any{999.0}, host["pressure.cpu.some_total_us"])
}

func TestEmitter_CPUAffinity_FullListParsedBeforeCap(t *testing.T) {
	root := t.TempDir()
	proc, sys := filepath.Join(root, "proc"), filepath.Join(root, "sys")

	// >256 chars, and truncating before parsing would cut "150-151" to the invalid range "150-15".
	allowed := strings.Repeat("0,", 125) + "150-151"
	require.Greater(t, len(allowed), 256)

	writeFile(t, filepath.Join(proc, "100", "status"),
		"Name:\tpython\nCpus_allowed_list:\t"+allowed+"\n")
	writeFile(t, filepath.Join(sys, "devices", "system", "cpu", "online"), "0-200\n")
	writeFile(
		t,
		filepath.Join(sys, "bus", "pci", "devices", "0000:1b:00.0", "local_cpulist"),
		"150-151\n",
	)

	h := newHarness(hostEnv(), rank17,
		withHost(provenance.HostPaths{ProcRoot: proc, SysRoot: sys, Pid: 100}))
	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	rank := h.decoded(t)[0]["rank"].(map[string]any)
	assert.Equal(t, "partial", rank["cpu_affinity"])
	assert.Len(t, rank["cpus_allowed"].(string), 256)
}

func TestEmitter_CPUAffinity(t *testing.T) {
	tests := []struct{ allowed, want string }{
		{"0-7", "unbound"},
		{"0-1", "local"},
		{"2-5", "partial"},
		{"4-5,7", "remote"},
	}
	for _, tt := range tests {
		t.Run(tt.allowed, func(t *testing.T) {
			h := newHarness(hostEnv(), rank17, withHost(fakeHost(t, tt.allowed, true)))

			h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

			assert.Equal(t, tt.want, h.decoded(t)[0]["rank"].(map[string]any)["cpu_affinity"])
		})
	}
}
