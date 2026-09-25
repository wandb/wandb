package leet_test

import (
	"bytes"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestPrintSummary(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	path := writeWandbFile(t,
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
	require.NoError(t, leet.PrintSummary(path, "", &text))
	assert.Contains(t, text.String(), "my-run (abc123)")
	assert.Contains(t, text.String(), "failed (exit code 1)")
	assert.Regexp(t, `step\s+4\n`, text.String())
	assert.Regexp(t, `loss\s+0.25\n`, text.String())
	assert.Regexp(t, `batch\s+32\n`, text.String())
	assert.Contains(t, text.String(), "[stderr] boom")
	assert.NotContains(t, text.String(), "_wandb")

}
