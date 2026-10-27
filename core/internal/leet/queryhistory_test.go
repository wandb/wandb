package leet_test

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func historyRecord(step int64, items ...*spb.HistoryItem) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
		Step: &spb.HistoryStep{Num: step},
		Item: items,
	}}}
}

func item(key, valueJSON string) *spb.HistoryItem {
	return &spb.HistoryItem{Key: key, ValueJson: valueJSON}
}

func queryHistory(t *testing.T, path string, q leet.HistoryQuery) map[string]any {
	t.Helper()
	var out bytes.Buffer
	require.NoError(t, leet.QueryHistory("", path, "", q, &out))
	var obj map[string]any
	require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
	return obj
}

func TestQueryHistory_NaNValues(t *testing.T) {
	path := writeWandbFile(t,
		historyRecord(0, item("loss", "1")),
		historyRecord(1, item("loss", "NaN")),
		historyRecord(2, item("loss", "3")),
	)

	rows := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"loss"}})
	assert.Equal(t, []any{
		map[string]any{"_step": 0.0, "loss": 1.0},
		map[string]any{"_step": 1.0, "loss": "NaN"},
		map[string]any{"_step": 2.0, "loss": 3.0},
	}, rows["rows"])

	bins := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"loss"}, Bins: 1})
	series := bins["series"].([]any)[0].(map[string]any)
	assert.EqualValues(t, 3, series["count"])
	assert.Equal(t, []any{map[string]any{
		"x0": 0.0, "x1": 2.0, "count": 2.0, "has_nan": true,
		"min": 1.0, "max": 3.0, "avg": 2.0, "last": 3.0,
	}}, series["bins"])
}

func TestQueryHistory_CustomAxisSurvivesCursor(t *testing.T) {
	path := writeWandbFile(
		t,
		&spb.Record{RecordType: &spb.Record_Metric{Metric: &spb.MetricRecord{
			GlobName: "train/*", StepMetric: "train/step",
		}}},
		historyRecord(0, item("train/step", "100"), item("train/loss", "0.5")),
		historyRecord(
			1,
			item("train/step", "200"),
			item("train/loss", "0.4"),
			item("train/acc", "0.9"),
		),
	)
	keys := []string{"train/loss", "train/acc"}

	first := queryHistory(t, path, leet.HistoryQuery{Keys: keys, Limit: 1})
	assert.Equal(t, map[string]any{"train/loss": "train/step"}, first["axes"])
	assert.Equal(t, []any{
		map[string]any{"_step": 0.0, "train/loss": 0.5, "train/step": 100.0},
	}, first["rows"])
	assert.Equal(t, true, first["has_more"])

	second := queryHistory(t, path, leet.HistoryQuery{
		Keys: keys, After: first["next_cursor"].(string),
	})
	assert.Equal(t, map[string]any{
		"train/loss": "train/step", "train/acc": "train/step",
	}, second["axes"])
	assert.Equal(t, []any{
		map[string]any{"_step": 1.0, "train/loss": 0.4, "train/acc": 0.9, "train/step": 200.0},
	}, second["rows"])
	assert.Equal(t, false, second["has_more"])
	assert.EqualValues(t, 1, second["total_steps"])
}

func TestQueryHistory_ExitRecordBeyondTheFirstPage(t *testing.T) {
	records := []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "long"}}},
	}
	pad := `"` + strings.Repeat("x", 512) + `"`
	for step := range int64(300) {
		records = append(records, historyRecord(step, item("loss", "1"), item("pad", pad)))
	}
	records = append(records, &spb.Record{
		RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 3}},
	})
	path := writeWandbFile(t, records...)

	out := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"loss"}, Limit: 1})
	assert.Equal(t, "failed", out["state"])
	assert.EqualValues(t, 3, out["exit_code"])
	assert.Equal(t, true, out["has_more"])
	assert.NotNil(t, out["next_cursor"])
}

func TestQueryHistory_GlobsSkipInternalKeysAndCrossSlashes(t *testing.T) {
	path := writeWandbFile(t, historyRecord(3,
		item("_runtime", "1.5"), item("a/b/c", "1"), item("a/x", "2"), item("ab", "3"),
		item("a/note", `"text"`),
	))

	glob := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"a/*"}})
	assert.Equal(t, []any{"a/b/c", "a/x"}, glob["keys"])
	assert.Equal(t, map[string]any{"a/note": "non_numeric"}, glob["skipped_keys"])

	all := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"*", "_runtime"}})
	assert.Equal(t, []any{"_runtime", "a/b/c", "a/x", "ab"}, all["keys"])

	none := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"A/*", "b/c"}})
	assert.Equal(t, []any{}, none["keys"])
	assert.Equal(t, []any{`no key matches "A/*"`, `no key matches "b/c"`}, none["warnings"])
}

func TestQueryHistory_SharedBinEdges(t *testing.T) {
	path := writeWandbFile(t,
		historyRecord(0, item("a", "1")),
		historyRecord(1, item("a", "2")),
		historyRecord(8, item("b", "3")),
		historyRecord(9, item("b", "4")),
	)

	out := queryHistory(t, path, leet.HistoryQuery{Keys: []string{"a", "b"}, Bins: 3})
	series := out["series"].([]any)
	a := series[0].(map[string]any)["bins"].([]any)[0].(map[string]any)
	b := series[1].(map[string]any)["bins"].([]any)[0].(map[string]any)
	assert.Equal(t, []any{0.0, 3.0}, []any{a["x0"], a["x1"]})
	assert.Equal(t, []any{6.0, 9.0}, []any{b["x0"], b["x1"]})
	assert.EqualValues(t, 2, a["count"])
	assert.EqualValues(t, 2, b["count"])
}

func TestQueryHistory_LastThenFollow(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "run-live.wandb")
		w, err := transactionlog.OpenWriter(path)
		require.NoError(t, err)
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
		}))
		for step := range int64(3) {
			require.NoError(t, w.Write(historyRecord(step, item("loss", "1"))))
		}
		require.NoError(t, w.Flush())

		var out bytes.Buffer
		done := make(chan error, 1)
		go func() {
			done <- leet.QueryHistory("", path, "",
				leet.HistoryQuery{Keys: []string{"loss"}, Last: 1, Follow: true}, &out)
		}()

		synctest.Wait()
		var first map[string]any
		require.NoError(t, json.Unmarshal(out.Bytes(), &first), out.String())
		assert.Equal(t, []any{map[string]any{"_step": 2.0, "loss": 1.0}}, first["rows"])
		assert.Equal(t, true, first["truncated"])
		assert.NotNil(t, first["next_cursor"])

		require.NoError(t, w.Write(historyRecord(3, item("loss", "2"))))
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
		}))
		require.NoError(t, w.Close())
		require.NoError(t, <-done)

		lines := bytes.Split(bytes.TrimSpace(out.Bytes()), []byte("\n"))
		require.Len(t, lines, 2)
		var last map[string]any
		require.NoError(t, json.Unmarshal(lines[1], &last))
		assert.Equal(t, []any{map[string]any{"_step": 3.0, "loss": 2.0}}, last["rows"])
		assert.Equal(t, "finished", last["state"])
		assert.EqualValues(t, 0, last["exit_code"])
		assert.Equal(t, false, last["has_more"])
		assert.Nil(t, last["next_cursor"])
	})
}
