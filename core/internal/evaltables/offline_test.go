package evaltables_test

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/evaltables"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func assertUUIDv7(t *testing.T, id string) {
	t.Helper()
	parsed, err := uuid.Parse(id)
	require.NoError(t, err)
	assert.Equal(t, uuid.Version(7), parsed.Version())
	assert.Equal(t, parsed.String(), id)
}

func TestNewRecord_NamesTableAndFirstVersion(t *testing.T) {
	data := &spb.EvalTableData{Name: "t", DatasetFields: outputFieldX, Rows: outputRows(2, 1)}

	record, err := evaltables.NewRecord(data, testRunPath, t.TempDir())

	require.NoError(t, err)
	assertUUIDv7(t, record.GetEvaluationId())
	assertUUIDv7(t, record.GetEvaluationVersionId())
	assert.NotEqual(t, record.GetEvaluationId(), record.GetEvaluationVersionId())
	assert.True(t, proto.Equal(data, record.GetTable()))
	assert.Empty(t, record.GetWandbRowsFile())
}

func TestNewRecord_CopiesWandbRowsFileIntoSyncDir(t *testing.T) {
	syncDir := t.TempDir()
	path := writeWandbRowsFile(t, &spb.EvalTableRow{Output: values(stringValue("1"))})
	data := &spb.EvalTableData{Name: "t", DatasetFields: outputFieldX, WandbRowsFilePath: path}

	record, err := evaltables.NewRecord(data, testRunPath, syncDir)

	require.NoError(t, err)
	assert.Equal(t,
		filepath.Join("eval-tables", record.GetEvaluationId()+".wandb-rows.gz"),
		record.GetWandbRowsFile())
	assert.Empty(t, record.GetTable().GetWandbRowsFilePath())
	assert.Equal(t, path, data.GetWandbRowsFilePath(), "NewRecord changed its input")
	original, err := os.ReadFile(path)
	require.NoError(t, err)
	copied, err := os.ReadFile(filepath.Join(syncDir, record.GetWandbRowsFile()))
	require.NoError(t, err)
	assert.Equal(t, original, copied)
	assert.Equal(t, []string{path}, filesIn(t, filepath.Dir(path)))
}

func TestNewRecord_RejectsInvalidTable(t *testing.T) {
	syncDir := t.TempDir()
	data := &spb.EvalTableData{
		Name:          "t",
		DatasetFields: []*spb.EvalTableField{{Source: "metadata", Name: "a", ValueType: "string"}},
	}

	_, err := evaltables.NewRecord(data, testRunPath, syncDir)

	assert.True(t, evaltables.IsUsageError(err), err)
	assert.Empty(t, filesIn(t, syncDir))
}

func TestEncodeRecord_UploadsWithTheRecordsIDsAndRows(t *testing.T) {
	syncDir := t.TempDir()
	path := writeWandbRowsFile(t, &spb.EvalTableRow{Output: values(stringValue("1"))})
	record, err := evaltables.NewRecord(
		&spb.EvalTableData{Name: "t", DatasetFields: outputFieldX, WandbRowsFilePath: path},
		testRunPath,
		syncDir,
	)
	require.NoError(t, err)
	// The client deletes its rows file after the response.
	require.NoError(t, os.Remove(path))
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)

	table, err := evaltables.EncodeRecord(record, testRunPath, syncDir)
	require.NoError(t, err)
	_, err = uploader.Upload(context.Background(), table)
	require.NoError(t, err)
	require.NoError(t, table.Close())

	requests := ces.Requests()
	require.Len(t, requests, 4)
	assert.Equal(t, record.GetEvaluationId(), bodyField(t, requests[0], "evaluation_id"))
	assert.Equal(t,
		record.GetEvaluationVersionId(),
		bodyField(t, requests[0], "evaluation_version_id"))
	assert.Equal(t,
		`{"rows":[{"input":null,"output":{"x":"1"},"scores":{}}]}`,
		requests[2].Body)
	// Keys derive from the evaluation ID, so that syncing the run again
	// replays the first sync's requests.
	for _, request := range requests {
		assert.True(t,
			strings.HasPrefix(
				request.IdempotencyKey,
				"wandb-eval-table-v3-"+record.GetEvaluationId()+"-"),
			request.IdempotencyKey)
	}
	assert.Equal(t,
		[]string{filepath.Join(syncDir, record.GetWandbRowsFile())},
		filesIn(t, filepath.Join(syncDir, "eval-tables")))
}

func TestEncodeRecord_RejectsRowsFileOutsideSyncDir(t *testing.T) {
	record := &spb.EvalTableRecord{
		Table:               &spb.EvalTableData{Name: "t"},
		EvaluationId:        uuid.Must(uuid.NewV7()).String(),
		EvaluationVersionId: uuid.Must(uuid.NewV7()).String(),
		WandbRowsFile:       filepath.Join("..", "rows.gz"),
	}

	_, err := evaltables.EncodeRecord(record, testRunPath, t.TempDir())

	assert.ErrorContains(t, err, "outside the sync directory")
}

func TestEncodeRecord_RejectsRecordWithoutIDs(t *testing.T) {
	record := &spb.EvalTableRecord{Table: &spb.EvalTableData{Name: "t"}}

	_, err := evaltables.EncodeRecord(record, testRunPath, t.TempDir())

	assert.ErrorContains(t, err, "no evaluation ID")
}
