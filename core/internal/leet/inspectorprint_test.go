package leet_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/transactionlog"
	txnlogtest "github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestDumpRecords_JSON(t *testing.T) {
	records := append(inspectorTestRecords(), &spb.Record{
		RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"val", "acc"}, ValueJson: "NaN"},
				{Key: "empty", ValueJson: "[]"},
			},
		}},
	})
	path := txnlogtest.WandbFile(t, records...)

	var out, notes bytes.Buffer
	require.NoError(t, leet.DumpRecords(path, "", &out, &notes, leet.DumpOptions{JSON: true}))
	assert.Empty(t, notes.String())

	var lines []map[string]any
	for line := range bytes.Lines(out.Bytes()) {
		var record map[string]any
		require.NoError(t, json.Unmarshal(line, &record), string(line))
		lines = append(lines, record)
	}
	require.Len(t, lines, 6)

	assert.Equal(t, "history", lines[1]["type"])
	assert.EqualValues(t, 2, lines[1]["num"])
	assert.Equal(t, map[string]any{
		"item": map[string]any{"loss": 0.5},
		"step": map[string]any{"num": 5.0},
	}, lines[1]["history"])
	assert.Equal(t, "STDERR", lines[2]["output_raw"].(map[string]any)["output_type"])
	assert.Equal(t, "request/partial_history", lines[3]["type"])
	assert.EqualValues(t, 7, lines[4]["exit"].(map[string]any)["exit_code"])
	assert.Equal(t,
		map[string]any{"val.acc": "NaN", "empty": []any{}},
		lines[5]["history"].(map[string]any)["item"])
}

func TestDumpRecords_FollowPrintsAppendedRecords(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "run-follow.wandb")
		w, err := transactionlog.OpenWriter(path)
		require.NoError(t, err)
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
		}))
		require.NoError(t, w.Flush())

		var out bytes.Buffer
		done := make(chan error, 1)
		go func() {
			done <- leet.DumpRecords(path, "", &out, io.Discard,
				leet.DumpOptions{JSON: true, Follow: true})
		}()

		synctest.Wait() // until the follower has printed the run record and waits for more
		assert.Contains(t, out.String(), `"type":"run"`)

		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_History{History: &spb.HistoryRecord{
				Item: []*spb.HistoryItem{{Key: "loss", ValueJson: "0.5"}},
			}},
		}))
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
		}))
		require.NoError(t, w.Close())

		require.NoError(t, <-done)
		assert.Contains(t, out.String(), `"loss":0.5`)
		assert.Contains(t, out.String(), `"exit_code":0`)
	})
}

func TestDumpRecords_FollowStopsForDeadRun(t *testing.T) {
	path := txnlogtest.WandbFile(t, inspectorTestRecords()[:2]...)
	hourAgo := time.Now().Add(-time.Hour)
	require.NoError(t, os.Chtimes(path, hourAgo, hourAgo))

	require.NoError(t, leet.DumpRecords(path, "", io.Discard, io.Discard,
		leet.DumpOptions{JSON: true, Follow: true, IdleTimeout: time.Minute}))
}

func TestPrintSummary(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	path := txnlogtest.WandbFile(t,
		&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
			RunId: "abc123", DisplayName: "my-run", Project: "proj",
			Config: &spb.ConfigRecord{Update: []*spb.ConfigItem{{Key: "lr", ValueJson: "0.1"}}},
		}}},
		&spb.Record{RecordType: &spb.Record_Config{Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{{Key: "batch", ValueJson: "32"}},
		}}},
		&spb.Record{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: 4},
			Item: []*spb.HistoryItem{{Key: "loss", ValueJson: "0.25"}},
		}}},
		&spb.Record{RecordType: &spb.Record_Summary{Summary: &spb.SummaryRecord{
			Update: []*spb.SummaryItem{
				{Key: "loss", ValueJson: "0.25"},
				{NestedKey: []string{"_wandb", "runtime"}, ValueJson: "3"},
			},
		}}},
		&spb.Record{RecordType: &spb.Record_OutputRaw{OutputRaw: &spb.OutputRawRecord{
			OutputType: spb.OutputRawRecord_STDOUT,
			Line:       "epoch 1\n",
			Timestamp:  timestamppb.New(at),
		}}},
		&spb.Record{RecordType: &spb.Record_OutputRaw{OutputRaw: &spb.OutputRawRecord{
			OutputType: spb.OutputRawRecord_STDERR,
			Line:       "boom\n",
			Timestamp:  timestamppb.New(at),
		}}},
		&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 1}}},
	)

	var text bytes.Buffer
	require.NoError(t, leet.PrintSummary(path, "", &text, false))
	assert.Contains(t, text.String(), "my-run (abc123)")
	assert.Contains(t, text.String(), "failed (exit code 1)")
	assert.Regexp(t, `step\s+4\n`, text.String())
	assert.Regexp(t, `loss\s+0.25\n`, text.String())
	assert.Regexp(t, `batch\s+32\n`, text.String())
	assert.Contains(t, text.String(), "[stderr] boom")
	assert.NotContains(t, text.String(), "_wandb")

	var out bytes.Buffer
	require.NoError(t, leet.PrintSummary(path, "", &out, true))
	var summary struct {
		State    string         `json:"state"`
		ExitCode int            `json:"exit_code"`
		Step     int            `json:"step"`
		Summary  map[string]any `json:"summary"`
		Config   map[string]any `json:"config"`
		Console  []struct {
			Stream, Line string
		} `json:"console"`
	}
	require.NoError(t, json.Unmarshal(out.Bytes(), &summary))
	assert.Equal(t, "failed", summary.State)
	assert.Equal(t, 1, summary.ExitCode)
	assert.Equal(t, 4, summary.Step)
	assert.Equal(t, map[string]any{"loss": 0.25}, summary.Summary)
	assert.Equal(t, map[string]any{"lr": 0.1, "batch": 32.0}, summary.Config)
	require.Len(t, summary.Console, 2)
	assert.Equal(t, "stderr", summary.Console[1].Stream)
	assert.Equal(t, "boom", summary.Console[1].Line)
}

func TestQuerySummary(t *testing.T) {
	nested := func(valueJSON string, path ...string) *spb.HistoryItem {
		return &spb.HistoryItem{NestedKey: path, ValueJson: valueJSON}
	}
	records := []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "abc123"}}},
		historyRecord(0, item("train/loss", "1"), item("val/loss", "2"), item("note", `"warmup"`)),
		historyRecord(1, item("train/loss", "NaN"),
			nested("4", "stats", "count"), nested(`"image-file"`, "img", "_type")),
		summaryRecord(
			&spb.SummaryItem{Key: "train/loss", ValueJson: "NaN"},
			&spb.SummaryItem{Key: "val/loss", ValueJson: "2"},
			&spb.SummaryItem{Key: "stats", ValueJson: `{"count": 4, "size": 10}`},
			&spb.SummaryItem{Key: "img", ValueJson: `{"_type": "image-file", "path": "i.png"}`},
		),
	}
	for i := range 51 {
		records = append(records,
			outputRecord(fmt.Sprintf("\x1b[31mline %d\x1b[0m\n", i), i == 50, time.Time{}))
	}
	path := writeWandbFile(t, records...)
	querySummary := func(q leet.SummaryQuery) map[string]any {
		var out bytes.Buffer
		require.NoError(t, leet.QuerySummary("", path, "", q, &out))
		var obj map[string]any
		require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
		return obj
	}

	all := querySummary(leet.SummaryQuery{})
	assert.Equal(t, "leet.summary/1", all["schema"])
	assert.Equal(t, map[string]any{
		"train/loss": map[string]any{"count": 2.0, "last": "NaN", "last_step": 1.0},
		"val/loss":   map[string]any{"count": 1.0, "last": 2.0, "last_step": 0.0},
		"note":       map[string]any{"count": 1.0, "last": "warmup", "last_step": 0.0},
	}, all["history_keys"])
	console := all["console"].([]any)
	require.Len(t, console, 50)
	assert.Equal(t, map[string]any{
		"number": 1.0, "timestamp": nil, "level": "", "label": "", "content": "line 1",
	}, console[0])
	assert.Equal(t, "error", console[49].(map[string]any)["level"])
	assert.EqualValues(t, 51, all["console_lines"])
	assert.Equal(t, []any{}, all["warnings"])

	some := querySummary(leet.SummaryQuery{Keys: []string{"val/*", "stats.count", "img", "nope"}})
	assert.Equal(t, map[string]any{
		"val/loss": 2.0,
		"stats":    map[string]any{"count": 4.0},
		"img":      map[string]any{"_type": "image-file", "path": "i.png"},
	}, some["summary"])
	assert.Equal(t, map[string]any{
		"val/loss": map[string]any{"count": 1.0, "last": 2.0, "last_step": 0.0},
	}, some["history_keys"])
	assert.Equal(t, []any{`no key matches "nope"`}, some["warnings"])
}
