package provenance_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o755))
	require.NoError(t, os.WriteFile(path, []byte(content), 0o644))
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

func TestV2HostCountersAndXPUGap(t *testing.T) {
	for _, exclude := range []int{0, 200} {
		dir := t.TempDir()
		host := fakeHost(t, "0-3", true)
		host.ExcludePid = exclude
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir, Host: host})
		require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
		emitter.OnSample(nil, assert.AnError)
		result := emitter.Drain()
		require.EqualValues(t, 1, result.Quality.Gaps)
		records := chunkRecords(t, dir)
		require.Len(t, records, 2)
		values := records[0]["host"].(map[string]any)
		if exclude == 0 {
			assert.Equal(t, 1015.0, values["sched.run_ns"])
		} else {
			assert.Equal(t, 1010.0, values["sched.run_ns"])
		}
		assert.Equal(t, 3.0, values["cgroup_cpu.nr_throttled"])
		assert.Equal(t, 42.0, values["pressure.cpu.some_total_us"])
		assert.Equal(t, "cgroup", records[0]["host_scope"])
	}
}

func TestV2HostPressureFallbackAndMissingValues(t *testing.T) {
	dir := t.TempDir()
	host := fakeHost(t, "0-3", false)
	writeFile(t, filepath.Join(host.ProcRoot, "pressure", "cpu"), "some avg10=NaN total=999\n")
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir, Host: host})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.OnSample(stats("gpu.process.0.gpu", "90"), nil)
	emitter.Drain()
	records := chunkRecords(t, dir)
	require.Len(t, records, 2)
	values := records[0]["host"].(map[string]any)
	assert.Equal(t, 999.0, values["pressure.cpu.some_total_us"])
	assert.NotContains(t, values, "pressure.cpu.some_avg10")
	assert.NotContains(t, values, "pressure.io.some_total_us")
	assert.Equal(t, "host", records[0]["host_scope"])
}
