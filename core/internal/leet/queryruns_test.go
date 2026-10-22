package leet_test

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type runsResponse struct {
	Runs      []map[string]any `json:"runs"`
	Total     int              `json:"total"`
	Truncated bool             `json:"truncated"`
}

func listRuns(t *testing.T, wandbDir string, q leet.RunsQuery) runsResponse {
	t.Helper()
	var out bytes.Buffer
	require.NoError(t, leet.ListRuns(wandbDir, "", q, &out))
	var obj runsResponse
	require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
	return obj
}

func summaryRecord(items ...*spb.SummaryItem) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Summary{
		Summary: &spb.SummaryRecord{Update: items},
	}}
}

func TestListRuns_TailOfALongFile(t *testing.T) {
	wandbDir := t.TempDir()
	key := "run-20250101_000000-long"
	records := []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "long"}}},
	}
	pad := `"` + strings.Repeat("x", 4096) + `"`
	for step := range int64(600) {
		records = append(records, historyRecord(step, item("loss", "1"), item("pad", pad)))
	}
	records = append(records,
		summaryRecord(&spb.SummaryItem{Key: "_step", ValueJson: "598"}),
		&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}},
	)
	createRunWandbFile(t, wandbDir, key, records)
	stat, err := os.Stat(filepath.Join(wandbDir, key, "run-long.wandb"))
	require.NoError(t, err)
	require.Greater(t, stat.Size(), int64(64*32*1024))
	require.NoError(t, os.WriteFile(filepath.Join(wandbDir, ".wandb-leet.json"),
		[]byte(`{"selected_runs":["`+key+`"],"pinned_run":"`+key+`"}`), 0o644))

	runs := listRuns(t, wandbDir, leet.RunsQuery{}).Runs
	require.Len(t, runs, 1)
	assert.Equal(t, "finished", runs[0]["state"])
	assert.EqualValues(t, 0, runs[0]["exit_code"])
	assert.EqualValues(t, 599, runs[0]["step"])
	assert.Equal(t, true, runs[0]["selected"])
	assert.Equal(t, true, runs[0]["pinned"])

	byDir := listRuns(t, filepath.Join(wandbDir, key), leet.RunsQuery{}).Runs
	require.Len(t, byDir, 1)
	assert.Equal(t, true, byDir[0]["pinned"])
}

func TestListRuns_FilterThenLimit(t *testing.T) {
	wandbDir := t.TempDir()
	createRunWandbFile(t, wandbDir, "run-20250101_000000-aaa", []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "aaa", Project: "vision"}}},
	})
	createRunWandbFile(t, wandbDir, "run-20250101_000001-bbb", nil)

	byField := listRuns(t, wandbDir, leet.RunsQuery{Filter: "project:vision"})
	require.Len(t, byField.Runs, 1)
	assert.Equal(t, "aaa", byField.Runs[0]["run_id"])

	cut := listRuns(t, wandbDir, leet.RunsQuery{Filter: "run-", Limit: 1})
	assert.Equal(t, 2, cut.Total)
	assert.True(t, cut.Truncated)
	require.Len(t, cut.Runs, 1)
	delete(cut.Runs[0], "file")
	delete(cut.Runs[0], "last_write")
	assert.Equal(t, map[string]any{
		"run_key":      "run-20250101_000001-bbb",
		"run_id":       nil,
		"name":         nil,
		"entity":       nil,
		"project":      nil,
		"state":        "unknown",
		"state_detail": "no run record yet",
		"start_time":   nil,
		"exit_code":    nil,
		"step":         nil,
		"tags":         []any{},
		"notes":        nil,
		"selected":     false,
		"pinned":       false,
	}, cut.Runs[0])
}

func TestListRuns_SummaryKeys(t *testing.T) {
	wandbDir := t.TempDir()
	createRunWandbFile(t, wandbDir, "run-20250101_000001-with", []*spb.Record{
		summaryRecord(
			&spb.SummaryItem{Key: "_step", ValueJson: "3"},
			&spb.SummaryItem{Key: "train/loss", ValueJson: "0.5"},
			&spb.SummaryItem{Key: "val/loss", ValueJson: "0.3"},
			&spb.SummaryItem{NestedKey: []string{"train/img", "_type"}, ValueJson: `"image-file"`},
			&spb.SummaryItem{NestedKey: []string{"train/img", "path"}, ValueJson: `"x.png"`},
		),
		summaryRecord(&spb.SummaryItem{Key: "train/loss", ValueJson: "0.4"}),
	})
	createRunWandbFile(t, wandbDir, "run-20250101_000000-without", []*spb.Record{
		historyRecord(0, item("loss", "1")),
	})

	runs := listRuns(t, wandbDir, leet.RunsQuery{SummaryKeys: []string{"train/*", "val/loss"}}).Runs
	require.Len(t, runs, 2)
	assert.Equal(t, map[string]any{
		"train/loss": 0.4,
		"train/img":  map[string]any{"_type": "image-file", "path": "x.png"},
		"val/loss":   0.3,
	}, runs[0]["summary"])
	assert.EqualValues(t, 3, runs[0]["step"])
	assert.Contains(t, runs[1], "summary")
	assert.Nil(t, runs[1]["summary"])
}
