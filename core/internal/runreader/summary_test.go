package runreader_test

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRun_ServerSideDerivedSummary(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-summary.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, writer.Close()) })

	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()

	appendRecords := func(records ...*spb.Record) {
		t.Helper()
		for _, record := range records {
			require.NoError(t, writer.Write(record))
		}
		require.NoError(t, writer.Flush())
		require.NoError(t, run.Update(context.Background()))
	}
	assertSummary := func(want string) {
		t.Helper()
		got, err := run.SummaryJSON()
		require.NoError(t, err)
		assert.JSONEq(t, want, string(got))
	}

	initial := runRecord("summary", nil)
	initial.GetRun().Telemetry = &spb.TelemetryRecord{
		Feature: &spb.Feature{ServerSideDerivedSummary: true},
	}
	appendRecords(initial,
		&spb.Record{RecordType: &spb.Record_Metric{Metric: &spb.MetricRecord{
			GlobName: "train.*", Summary: &spb.MetricSummary{Min: true, Max: true, Mean: true},
		}}},
		&spb.Record{RecordType: &spb.Record_Metric{Metric: &spb.MetricRecord{
			Name: "train.ignored", Summary: &spb.MetricSummary{None: true},
		}}},
		&spb.Record{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{Key: "loss", ValueJson: "2"},
				{NestedKey: []string{"train", "loss"}, ValueJson: "3"},
				{NestedKey: []string{"train", "ignored"}, ValueJson: "1"},
				{Key: "status", ValueJson: `"running"`},
			},
		}}},
	)
	assertSummary(`{"loss":2,"train":{"loss":{"min":3,"max":3,"mean":3}},"status":"running"}`)

	// A later run identity update need not repeat the initial telemetry.
	appendRecords(runRecord("summary", nil),
		&spb.Record{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: 1},
			Item: []*spb.HistoryItem{
				{Key: "loss", ValueJson: "0.5"},
				{NestedKey: []string{"train", "loss"}, ValueJson: "1"},
				{NestedKey: []string{"train", "ignored"}, ValueJson: "2"},
			},
		}}},
	)
	assertSummary(`{"loss":0.5,"train":{"loss":{"min":1,"max":3,"mean":2}},"status":"running"}`)

	// Polling again must not count the same history twice.
	require.NoError(t, run.Update(context.Background()))
	assertSummary(`{"loss":0.5,"train":{"loss":{"min":1,"max":3,"mean":2}},"status":"running"}`)

	appendRecords(&spb.Record{RecordType: &spb.Record_Summary{Summary: &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "loss", ValueJson: "99"},
			{NestedKey: []string{"train", "loss"}, ValueJson: "42"},
		},
		Remove: []*spb.SummaryItem{{Key: "status"}},
	}}})
	assertSummary(`{"loss":99,"train":{"loss":42}}`)
}

func TestRun_PreservesClientDerivedSummary(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-summary.wandb")
	writeLog(t, path, runRecord("summary", nil),
		&spb.Record{RecordType: &spb.Record_Metric{Metric: &spb.MetricRecord{
			Name: "loss", Summary: &spb.MetricSummary{Mean: true},
		}}},
		summaryRecord(map[string]string{"loss": `{"mean":2}`}),
		historyRecord(1, map[string]string{"loss": "1", "unreported": "3"}),
	)
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))
	summary, err := run.SummaryJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"loss":{"mean":2}}`, string(summary))
}
