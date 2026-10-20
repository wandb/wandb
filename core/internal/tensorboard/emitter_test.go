package tensorboard_test

import (
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/wbvalue"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func historyRecord(items []*spb.HistoryItem) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Item: items,
			},
		},
	}
}

func configRecord(items []*spb.ConfigItem) *spb.Record {
	return &spb.Record{
		RecordType: &spb.Record_Config{
			Config: &spb.ConfigRecord{
				Update: items,
			},
		},
	}
}

func assertProtoEqual(t *testing.T, expected, actual proto.Message) {
	assert.True(t,
		proto.Equal(expected, actual),
		"Value is\n\t%v\nbut expected\n\t%v", actual, expected)
}

func TestAccumulatesHistory(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(
		runhandle.New(),
		settings.From(&spb.Settings{}),
	)

	emitter.EmitHistory(pathtree.PathOf("x", "y"), "0.5")
	emitter.EmitHistory(pathtree.PathOf("z"), `"abc"`)
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)

	records := fakeRunWork.AllRecords()
	assert.Len(t, records, 1)
	assertProtoEqual(t,
		historyRecord([]*spb.HistoryItem{
			{Key: "_runtime", ValueJson: "0.000000"},
			{NestedKey: []string{"x", "y"}, ValueJson: "0.5"},
			{NestedKey: []string{"z"}, ValueJson: `"abc"`},
		}),
		records[0])
}

func TestRequiredKeys(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		runHandle := runhandle.New()
		runHandle.ResumeRunTimer()
		synctest.Sleep(time.Minute + time.Second)

		emitter := tensorboard.NewTFEmitter(
			runHandle,
			settings.From(&spb.Settings{}),
		)

		emitter.SetTFStep(9)
		emitter.SetTFWallTime(2.5)
		emitter.EmitHistory(pathtree.PathOf("x"), "4")
		fakeRunWork := runworktest.New()
		emitter.Emit(fakeRunWork)
		fakeRunWork.Close()

		records := fakeRunWork.AllRecords()
		assert.Len(t, records, 1)
		assertProtoEqual(t,
			historyRecord([]*spb.HistoryItem{
				{Key: "_runtime", ValueJson: "61.000000"},
				{NestedKey: []string{"x"}, ValueJson: "4"},
				{Key: "global_step", ValueJson: "9"},
				{Key: "_timestamp", ValueJson: "2.5"},
			}),
			records[0])
	})
}

func TestChartModifiesConfig(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(
		runhandle.New(),
		settings.From(&spb.Settings{}),
	)
	chart := wbvalue.Chart{Title: "test-title"}
	expectedConfigJSON, err := chart.ConfigValueJSON()
	require.NoError(t, err)

	require.NoError(t,
		emitter.EmitChart("mychart", chart))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)
	fakeRunWork.Close()

	records := fakeRunWork.AllRecords()
	assert.Len(t, records, 1)
	assertProtoEqual(t,
		configRecord([]*spb.ConfigItem{
			{
				NestedKey: chart.ConfigKey("mychart").Labels(),
				ValueJson: expectedConfigJSON},
		}),
		records[0])
}

func TestTableWritesToFile(t *testing.T) {
	s := settings.From(&spb.Settings{
		SyncDir: wrapperspb.String(t.TempDir()),
	})
	emitter := tensorboard.NewTFEmitter(runhandle.New(), s)
	table := wbvalue.Table{
		ColumnLabels: []string{"a", "b"},
		Rows:         [][]any{{1, 2}, {3, 4}},
	}

	require.NoError(t,
		emitter.EmitTable(pathtree.PathOf("my", "table"), table))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)
	fakeRunWork.Close()

	records := fakeRunWork.AllRecords()
	require.Len(t, records, 2) // file upload & history
	filesRecord := records[0].GetFiles()
	require.NotNil(t, filesRecord)
	require.Len(t, filesRecord.Files, 1)
	assert.Regexp(t,
		`media/table/[a-z0-9]{32}\.table\.json`,
		filepath.ToSlash(filesRecord.Files[0].Path))
	assert.FileExists(t,
		filepath.Join(s.GetFilesDir(), filesRecord.Files[0].Path))
}

func TestTableUpdatesHistory(t *testing.T) {
	emitter := tensorboard.NewTFEmitter(
		runhandle.New(),
		settings.From(&spb.Settings{
			SyncDir: wrapperspb.String(t.TempDir()),
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
	fakeRunWork.Close()

	records := fakeRunWork.AllRecords()
	require.Len(t, records, 2)
	history := records[1].GetHistory()
	require.NotNil(t, history)
	require.Len(t, history.Item, 2)
	assert.Equal(t, history.Item[1].NestedKey, []string{"my", "table"})
}

func TestEmitImages(t *testing.T) {
	s := settings.From(&spb.Settings{
		SyncDir: wrapperspb.String(t.TempDir()),
	})
	emitter := tensorboard.NewTFEmitter(runhandle.New(), s)
	require.NoError(t,
		emitter.EmitImages(
			pathtree.PathOf("my", "image"),
			[]wbvalue.Image{
				{
					Width:       2,
					Height:      2,
					EncodedData: []byte{0, 1, 2, 3},
					Format:      "png",
				},
				{
					Width:       2,
					Height:      2,
					EncodedData: []byte{0, 1, 2, 3},
					Format:      "png",
				},
			},
		))
	fakeRunWork := runworktest.New()
	emitter.Emit(fakeRunWork)
	fakeRunWork.Close()

	records := fakeRunWork.AllRecords()
	require.Len(t, records, 2) // file upload & history
	filesRecord := records[0].GetFiles()
	require.NotNil(t, filesRecord)
	require.Len(t, filesRecord.Files, 2)

	for _, file := range filesRecord.Files {
		assert.Regexp(t,
			`media/images/[a-z0-9]{32}\.png`,
			filepath.ToSlash(file.Path))
		assert.FileExists(t, filepath.Join(s.GetFilesDir(), file.Path))
	}
}
