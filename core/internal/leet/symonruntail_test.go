package leet

import (
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRunTail_FollowsNameStepAndLoss(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc123.wandb")
	writer, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, writer.Write(&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
		RunId: "abc123", DisplayName: "dazzling-owl-42", Project: "nlp",
		StartTime: timestamppb.Now(),
	}}}))
	now := float64(time.Now().Unix())
	for step, loss := range []string{"2.0", "1.5", "1.1"} {
		at := strconv.FormatFloat(now+float64(step)/10, 'f', 1, 64)
		history := &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: int64(step)},
			Item: []*spb.HistoryItem{
				{Key: "_timestamp", ValueJson: at},
				{Key: "acc", ValueJson: "0.5"},
				{Key: "loss", ValueJson: loss},
			},
		}
		require.NoError(t, writer.Write(&spb.Record{
			RecordType: &spb.Record_History{History: history},
		}))
	}
	require.NoError(t, writer.Close())

	tail := openRunTail(path, observability.NewNoOpLogger())
	defer tail.close()
	tail.read(runTailBudget)

	require.Equal(t, "dazzling-owl-42", tail.run.Name)
	require.Equal(t, "nlp", tail.run.Project)
	require.Equal(t, int64(2), tail.run.Step)
	require.Equal(t, "loss", tail.run.Metric)
	require.Equal(t, []float64{2, 1.5, 1.1}, tail.run.Values)
	require.InDelta(t, 10, tail.run.StepRate, 1e-6)
}
