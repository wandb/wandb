package tensorboard_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/wbvalue"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func localFlushPartialHistory(items []*spb.HistoryItem) *spb.Record {
	return &spb.Record{
		Control: &spb.Control{Local: true},
		RecordType: &spb.Record_Request{
			Request: &spb.Request{
				RequestType: &spb.Request_PartialHistory{
					PartialHistory: &spb.PartialHistoryRequest{
						Item: items,
						Action: &spb.HistoryAction{
							Flush: true,
						},
					},
				},
			},
		},
	}
}

func localConfigUpdate(items []*spb.ConfigItem) *spb.Record {
	return &spb.Record{
		Control: &spb.Control{Local: true},
		RecordType: &spb.Record_Config{
			Config: &spb.ConfigRecord{
				Update: items,
			},
		},
	}
}

func assertProtoEqual(t *testing.T, expected proto.Message, actual proto.Message) {
	assert.True(t,
		proto.Equal(expected, actual),
		"Value is\n\t%v\nbut expected\n\t%v", actual, expected)
}

func TestAccumulatesHistory(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(settings.From(&spb.Settings{}))

	emitter.EmitHistory(pathtree.PathOf("x", "y"), "0.5")
	emitter.EmitHistory(pathtree.PathOf("z"), `"abc"`)
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	assert.Len(t, records, 1)
	assertProtoEqual(t,
		localFlushPartialHistory([]*spb.HistoryItem{
			{NestedKey: []string{"x", "y"}, ValueJson: "0.5"},
			{NestedKey: []string{"z"}, ValueJson: `"abc"`},
		}),
		records[0])
}

func TestStepAndWallTime(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(settings.From(&spb.Settings{}))

	emitter.SetTFStep(pathtree.PathOf("train", "global_step"), 9)
	emitter.SetTFWallTime(2.5)
	emitter.EmitHistory(pathtree.PathOf("x"), "4")
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	assert.Len(t, records, 1)
	assertProtoEqual(t,
		localFlushPartialHistory([]*spb.HistoryItem{
			{NestedKey: []string{"x"}, ValueJson: "4"},
			{NestedKey: []string{"train", "global_step"}, ValueJson: "9"},
			{Key: "_timestamp", ValueJson: "2.5"},
		}),
		records[0])
}

func TestChartModifiesConfig(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(settings.From(&spb.Settings{}))
	chart := wbvalue.Chart{Title: "test-title"}
	expectedConfigJSON, err := chart.ConfigValueJSON()
	require.NoError(t, err)

	require.NoError(t,
		emitter.EmitChart("mychart", chart))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	assert.Len(t, records, 1)
	assertProtoEqual(t,
		localConfigUpdate([]*spb.ConfigItem{
			{
				NestedKey: chart.ConfigKey("mychart").Labels(),
				ValueJson: expectedConfigJSON},
		}),
		records[0])
}

func TestTableWritesToFile(t *testing.T) {
	tmpdir := t.TempDir()
	emitter := tensorboard.NewTFEmitter(
		settings.From(&spb.Settings{
			FilesDir: wrapperspb.String(tmpdir),
		}),
	)
	table := wbvalue.Table{
		ColumnLabels: []string{"a", "b"},
		Rows:         [][]any{{1, 2}, {3, 4}},
	}

	require.NoError(t,
		emitter.EmitTable(pathtree.PathOf("my", "table"), table))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	require.Len(t, records, 2) // file upload & history
	filesRecord := records[0].GetFiles()
	require.NotNil(t, filesRecord)
	require.Len(t, filesRecord.Files, 1)
	assert.Regexp(t,
		`media/table/[a-z0-9]{32}\.table\.json`,
		filepath.ToSlash(filesRecord.Files[0].Path))
	assert.FileExists(t, filepath.Join(tmpdir, filesRecord.Files[0].Path))
}

func TestTableUpdatesHistory(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(
		settings.From(&spb.Settings{
			FilesDir: wrapperspb.String(t.TempDir()),
		}),
	)
	table := wbvalue.Table{
		ColumnLabels: []string{"a", "b"},
		Rows:         [][]any{{1, 2}, {3, 4}},
	}

	require.NoError(t,
		emitter.EmitTable(pathtree.PathOf("my", "table"), table))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	require.Len(t, records, 2)
	partialHistory := records[1].GetRequest().GetPartialHistory()
	require.NotNil(t, partialHistory)
	require.Len(t, partialHistory.Item, 1)
	assert.Equal(t, partialHistory.Item[0].NestedKey, []string{"my", "table"})
}
