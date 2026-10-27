package leet_test

import (
	"bytes"
	"encoding/json"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// statsRecord returns a stats record taken at `at` with the given
// key, value_json pairs.
func statsRecord(at time.Time, kv ...string) *spb.Record {
	stats := &spb.StatsRecord{Timestamp: timestamppb.New(at)}
	for i := 0; i+1 < len(kv); i += 2 {
		stats.Item = append(stats.Item, &spb.StatsItem{Key: kv[i], ValueJson: kv[i+1]})
	}
	return &spb.Record{RecordType: &spb.Record_Stats{Stats: stats}}
}

func querySystem(t *testing.T, path string, q leet.SystemQuery) map[string]any {
	t.Helper()
	var out bytes.Buffer
	require.NoError(t, leet.QuerySystem("", path, "", q, &out))
	var obj map[string]any
	require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
	return obj
}

func TestQuerySystem_RowsAndBins(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	ts := float64(at.Unix())
	path := writeWandbFile(t,
		statsRecord(at, "cpu", "10", "network.recv", "1024", "custom", "1"),
		statsRecord(at.Add(10*time.Second), "gpu.0.gpu", "NaN", "cpu", "30"),
		statsRecord(at, "gpu.0.gpu", "50", "gpu.0.gpu/l:node1", "70",
			"gpu.0.powerWatts", "100", "gpu.0.temp", "60", "disk./.usageGB", "1"),
	)

	rows := querySystem(t, path, leet.SystemQuery{})
	assert.Equal(t, "_timestamp", rows["x_axis"])
	assert.Equal(t, []any{
		"system.cpu", "system.custom", "system.disk./.usageGB", "system.gpu.0.gpu",
		"system.gpu.0.gpu/l:node1", "system.gpu.0.powerWatts", "system.gpu.0.temp",
		"system.network.recv",
	}, rows["keys"])
	assert.Equal(t, []any{
		map[string]any{
			"_timestamp": ts, "system.cpu": 10.0, "system.network.recv": 1024.0,
			"system.custom": 1.0, "system.gpu.0.gpu": 50.0, "system.gpu.0.gpu/l:node1": 70.0,
			"system.gpu.0.powerWatts": 100.0, "system.gpu.0.temp": 60.0,
			"system.disk./.usageGB": 1.0,
		},
		map[string]any{"_timestamp": ts + 10, "system.gpu.0.gpu": "NaN", "system.cpu": 30.0},
	}, rows["rows"])

	bins := querySystem(t, path, leet.SystemQuery{Bins: 1})
	series := make(map[string]map[string]any)
	for _, s := range bins["series"].([]any) {
		series[s.(map[string]any)["key"].(string)] = s.(map[string]any)
	}
	assert.Equal(t, "GPU Utilization", series["system.gpu.0.gpu"]["title"])
	assert.Equal(t, "%", series["system.gpu.0.gpu"]["unit"])
	assert.Equal(t, "W", series["system.gpu.0.powerWatts"]["unit"])
	assert.Equal(t, "°C", series["system.gpu.0.temp"]["unit"])
	assert.Equal(t, "GiB", series["system.disk./.usageGB"]["unit"])
	assert.Equal(t, []any{map[string]any{
		"x0": ts, "x1": ts + 10, "count": 1.0, "has_nan": true,
		"min": 50.0, "max": 50.0, "avg": 50.0, "last": 50.0,
	}}, series["system.gpu.0.gpu"]["bins"])
	assert.Equal(t, []any{map[string]any{
		"x0": ts, "x1": ts + 10, "count": 1.0, "has_nan": false,
		"min": 1024.0, "max": 1024.0, "avg": 1024.0, "last": 1024.0,
	}}, series["system.network.recv"]["bins"])
	assert.Equal(t, "GPU Utilization", series["system.gpu.0.gpu/l:node1"]["title"])
	assert.Nil(t, series["system.custom"]["title"])
	assert.Nil(t, series["system.custom"]["unit"])
}

func TestQuerySystem_SinceLastAndLimit(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	path := writeWandbFile(t,
		statsRecord(at, "cpu", "1"),
		statsRecord(at.Add(30*time.Second), "cpu", "2"),
		statsRecord(at.Add(time.Minute), "cpu", "3"),
		&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{}}},
	)

	out := querySystem(t, path, leet.SystemQuery{Since: "30s"})
	assert.Equal(t, "finished", out["state"])
	assert.Equal(t, []any{
		map[string]any{"_timestamp": float64(at.Unix()) + 30, "system.cpu": 2.0},
		map[string]any{"_timestamp": float64(at.Unix()) + 60, "system.cpu": 3.0},
	}, out["rows"])
	coverage := out["coverage"].(map[string]any)
	assert.Equal(t, "2026-09-23T12:00:30Z", coverage["requested_since"])

	now := time.Now().Truncate(time.Second)
	live := writeWandbFile(t,
		&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}}},
		statsRecord(now.Add(-200*time.Second), "cpu", "1"),
		statsRecord(now.Add(-30*time.Second), "cpu", "2"),
	)
	out = querySystem(t, live, leet.SystemQuery{Since: "3m"})
	assert.Equal(t, "running", out["state"])
	assert.Equal(t, []any{
		map[string]any{"_timestamp": float64(now.Unix()) - 30, "system.cpu": 2.0},
	}, out["rows"])

	last := querySystem(t, path, leet.SystemQuery{Last: 1})
	assert.Equal(t, []any{
		map[string]any{"_timestamp": float64(at.Unix()) + 60, "system.cpu": 3.0},
	}, last["rows"])
	assert.Equal(t, true, last["truncated"])

	limit := querySystem(t, path, leet.SystemQuery{Limit: 2})
	assert.Equal(t, []any{
		map[string]any{"_timestamp": float64(at.Unix()), "system.cpu": 1.0},
		map[string]any{"_timestamp": float64(at.Unix()) + 30, "system.cpu": 2.0},
	}, limit["rows"])
	assert.Equal(t, true, limit["truncated"])
}

func TestQuerySystem_KeysGlob(t *testing.T) {
	path := writeWandbFile(t,
		statsRecord(time.Now(), "gpu.0.gpu", "1", "gpu.1.gpu", "2", "cpu", "3"),
	)

	out := querySystem(t, path, leet.SystemQuery{Keys: []string{"system.gpu.*", "system.tpu.*"}})
	assert.Equal(t, []any{"system.gpu.0.gpu", "system.gpu.1.gpu"}, out["keys"])
	assert.Equal(t, []any{`no key matches "system.tpu.*"`}, out["warnings"])
}
