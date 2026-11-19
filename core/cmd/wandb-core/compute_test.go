package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func runComputeCommand(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	cmd, opts, err := parseLeetArgs(append([]string{"compute"}, args...))
	require.NoError(t, err)
	stdout, err := os.CreateTemp(t.TempDir(), "stdout")
	require.NoError(t, err)
	defer stdout.Close()
	stderr, err := os.CreateTemp(t.TempDir(), "stderr")
	require.NoError(t, err)
	defer stderr.Close()
	oldOut, oldErr := os.Stdout, os.Stderr
	os.Stdout, os.Stderr = stdout, stderr
	defer func() { os.Stdout, os.Stderr = oldOut, oldErr }()
	code := cmd.run(opts, nil)
	out, err := os.ReadFile(stdout.Name())
	require.NoError(t, err)
	errOut, err := os.ReadFile(stderr.Name())
	require.NoError(t, err)
	return code, string(out), string(errOut)
}

func assertComputeRequest(t *testing.T, r *http.Request, method string) string {
	t.Helper()
	assert.Equal(t, http.MethodPost, r.Method)
	assert.Equal(t, "/compute.v1.ComputeService/"+method, r.URL.Path)
	assert.Equal(t, "application/json", r.Header.Get("Content-Type"))
	username, password, ok := r.BasicAuth()
	assert.True(t, ok)
	assert.Equal(t, "api", username)
	assert.Equal(t, "compute-test-key", password)
	body, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	return string(body)
}

func TestLeetComputeUsage(t *testing.T) {
	t.Setenv("WANDB_API_KEY", "compute-test-key")
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body := assertComputeRequest(t, r, "ComputeUsage")
		period := `{"start":"2026-10-01","end":"2026-10-31"}`
		if calls.Add(1) == 2 {
			period = `{"start":"2026-09-01","end":"2026-09-30"}`
		}
		assert.JSONEq(t, `{
			"scope":{"org":"acme","user":"alice","tags":["training","nightly,large"]},
			"period":`+period+`,"basis":"BASIS_PHYSICAL",
			"group_by":["GROUP_BY_TEAM","GROUP_BY_DEVICE_MODEL"],
			"filters":{"device_models":["H100","A100"],"device_types":["nvidia_gpu","amd_gpu"]}
		}`, body)
		w.Header().Set("Content-Type", "application/json")
		if calls.Load() == 2 {
			_, _ = io.WriteString(
				w,
				`{"schema":"compute.usage/1","definition_version":"compute-defs/1",`+
					`"basis":"physical","period":`+period+`,"rows":[]}`,
			)
			return
		}
		_, _ = io.WriteString(w, `{
			"schema":"compute.usage/1","definition_version":"compute-defs/1","basis":"physical",
			"period":`+period+`,"as_of":"2026-11-04T18:02:11Z","rows":[
				{"group":{"team":"training"},"gpu_hours":12.5,"assigned_idle_gpu_hours":0,
				 "runs":6,"devices":4,"hardware":{"H100":12.5},
				 "gpu_utilization_ratio":0.9,"tensor_active_ratio":0.6,"power_w":400,"energy_kwh":5,
				 "coverage":{"observed_share":0.99,"uuid_share":1,"process_share":1,
				 "writers_reporting":2,"writers_expected":4,"allocation":"unavailable"}},
				{"group":{"team":"without-samples"},"runs":1,
				 "coverage":{"runs_without_samples":1,"allocation":"unavailable"}}
			]
		}`)
	}))
	defer server.Close()

	code, out, errOut := runComputeCommand(t, "usage", "--period", "2026-10", "--compare",
		"--basis", "physical", "--group-by", "team,device_model", "--user", "alice",
		"--tag", "training", "--tag", "nightly,large", "--device-model", "H100",
		"--device-model", "A100", "--device-type", "nvidia_gpu", "--device-type", "amd_gpu",
		"--remote-url", server.URL+"/orgs/acme")
	require.Equal(t, exitCodeSuccess, code, errOut)
	assert.Empty(t, errOut)
	assert.EqualValues(t, 2, calls.Load())
	var obj map[string]any
	require.NoError(t, json.Unmarshal([]byte(out), &obj))
	assert.Len(t, obj, 11)
	for _, key := range []string{"schema", "definition_version", "basis", "period", "as_of",
		"retrieval_method", "rows", "truncated", "source", "warnings", "compare"} {
		assert.Contains(t, obj, key)
	}
	assert.Equal(t, "leet.compute.usage/1", obj["schema"])
	assert.Equal(t, "compute-defs/1", obj["definition_version"])
	assert.Equal(t, "physical", obj["basis"])
	assert.Equal(t, "2026-11-04T18:02:11Z", obj["as_of"])
	assert.Equal(t, "api", obj["retrieval_method"])
	assert.Equal(t, false, obj["truncated"])
	assert.Equal(t, []any{}, obj["warnings"])
	assert.Equal(t, map[string]any{
		"kind": "remote", "path": nil, "url": server.URL + "/orgs/acme", "org": "acme",
		"entity": nil, "project": nil, "run_id": nil,
	}, obj["source"])
	assert.Equal(t, map[string]any{"start": "2026-10-01", "end": "2026-10-31"}, obj["period"])
	assert.Equal(t, map[string]any{
		"period": map[string]any{"start": "2026-09-01", "end": "2026-09-30"}, "rows": []any{},
	}, obj["compare"])
	rows := obj["rows"].([]any)
	require.Len(t, rows, 2)
	first := rows[0].(map[string]any)
	assert.Equal(t, 12.5, first["gpu_hours"])
	assert.Equal(t, 0.0, first["assigned_idle_gpu_hours"])
	assert.Equal(t, 6.0, first["runs"])
	assert.Equal(t, 4.0, first["devices"])
	assert.Equal(t, map[string]any{"H100": 12.5}, first["hardware"])
	assert.Equal(t, 4.0, first["coverage"].(map[string]any)["writers_expected"])
	missing := rows[1].(map[string]any)
	for _, field := range []string{"gpu_hours", "assigned_idle_gpu_hours", "gpu_utilization_ratio",
		"tensor_active_ratio", "power_w", "energy_kwh"} {
		assert.Contains(t, missing, field)
		assert.Nil(t, missing[field], field)
	}
	coverage := missing["coverage"].(map[string]any)
	assert.Contains(t, coverage, "writers_expected")
	assert.Nil(t, coverage["writers_expected"])
	assert.Equal(t, 1.0, coverage["runs_without_samples"])
}

func TestLeetComputeDrilldown(t *testing.T) {
	t.Setenv("WANDB_API_KEY", "compute-test-key")
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		body := assertComputeRequest(t, r, "ComputeDrilldown")
		assert.JSONEq(t, `{
			"team":"training","project":"pretrain","run":"abc123",
			"fields":["accelerators.nvidia.sm_active_ratio","accelerators.nvidia.pipe_tensor_active_ratio"],
			"bins":2,"device":"GPU-123","start":"2026-10-01T00:00:00Z","end":"2026-10-01T00:01:00Z"
		}`, body)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{
			"schema":"compute.drilldown/1","definition_version":"compute-defs/1",
			"as_of":"2026-11-04T18:02:11Z","start":"2026-10-01T00:00:00Z","end":"2026-10-01T00:01:00Z",
			"series":[{"field":"accelerators.nvidia.sm_active_ratio","device_uuid":"GPU-123",
			 "device_index":0,"device_type":"nvidia_gpu","model":"H100","binding":"process",
			 "writer_id":"writer-1","writer_label":"node-1","rank":0,"hostname":"host-1",
			 "bins":[{"start":"2026-10-01T00:00:30Z","count":17,"min":0.2,"max":0.8,"avg":0.5,"last":0.4}]},
			 {"field":"accelerators.nvidia.pipe_tensor_active_ratio","device_uuid":"GPU-123"}]
		}`)
	}))
	defer server.Close()

	code, out, errOut := runComputeCommand(t, "drilldown", "--fields",
		"accelerators.nvidia.sm_active_ratio,accelerators.nvidia.pipe_tensor_active_ratio",
		"--bins", "2", "--device", "GPU-123", "--start", "2026-10-01T01:00:00+01:00",
		"--end", "2026-10-01T00:01:00Z", server.URL+"/training/pretrain/runs/abc123")
	require.Equal(t, exitCodeSuccess, code, errOut)
	assert.Empty(t, errOut)
	assert.EqualValues(t, 1, calls.Load())
	var obj map[string]any
	require.NoError(t, json.Unmarshal([]byte(out), &obj))
	assert.Equal(t, "leet.compute.drilldown/1", obj["schema"])
	assert.Equal(t, "compute-defs/1", obj["definition_version"])
	assert.Equal(t, "2026-11-04T18:02:11Z", obj["as_of"])
	assert.Equal(t, "api", obj["retrieval_method"])
	assert.Equal(t, false, obj["truncated"])
	assert.Equal(t, []any{}, obj["warnings"])
	assert.Equal(t, map[string]any{
		"kind": "remote", "path": nil, "url": server.URL + "/training/pretrain/runs/abc123",
		"entity": "training", "project": "pretrain", "run_id": "abc123",
	}, obj["source"])
	series := obj["series"].([]any)
	require.Len(t, series, 2)
	start := float64(time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC).Unix())
	assert.Equal(t, map[string]any{
		"field": "accelerators.nvidia.sm_active_ratio", "device_uuid": "GPU-123",
		"device_index": 0.0, "device_type": "nvidia_gpu", "model": "H100",
		"parent_uuid": "", "profile": "", "binding": "process", "writer_id": "writer-1",
		"writer_label": "node-1", "rank": 0.0, "hostname": "host-1", "attributes": "",
		"bins": []any{map[string]any{
			"x0": start + 30, "x1": start + 60, "count": 17.0, "min": 0.2,
			"max": 0.8, "avg": 0.5, "last": 0.4, "has_nan": false,
		}},
	}, series[0])
	second := series[1].(map[string]any)
	assert.Contains(t, second, "rank")
	assert.Nil(t, second["rank"])
	assert.Equal(t, []any{}, second["bins"])
}

func TestLeetComputeConnectError(t *testing.T) {
	t.Setenv("WANDB_API_KEY", "compute-test-key")
	for _, tc := range []struct {
		code   string
		status int
		want   string
	}{
		{"invalid_argument", http.StatusBadRequest, "bad_request"},
		{"not_found", http.StatusNotFound, "run_not_found"},
		{"permission_denied", http.StatusForbidden, "not_available"},
		{"unavailable", http.StatusServiceUnavailable, "not_available"},
	} {
		t.Run(tc.code, func(t *testing.T) {
			server := httptest.NewServer(
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					body := assertComputeRequest(t, r, "ComputeUsage")
					assert.JSONEq(
						t,
						`{"scope":{"team":"training","project":"pretrain","runs":["abc123"]},`+
							`"period":{"start":"2026-10-01","end":"2026-10-31"},"basis":"BASIS_PHYSICAL"}`,
						body,
					)
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(tc.status)
					_, _ = io.WriteString(w, `{"code":"`+tc.code+`","message":"server says no"}`)
				}),
			)
			defer server.Close()
			code, out, errOut := runComputeCommand(t, "usage", "--period", "2026-10",
				"--remote-url", server.URL+"/training/pretrain/runs/abc123")
			assert.Equal(t, exitCodeErrorInternal, code)
			assert.Empty(t, out)
			assert.JSONEq(
				t,
				`{"schema":"leet.error/1","error":"`+tc.want+`","message":"server says no"}`,
				errOut,
			)
		})
	}
}
