package evaltables

import (
	"errors"
	"fmt"
	"path/filepath"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// recordRowsDir is where NewRecord keeps W&B rows files, relative to the
// run's sync directory.
const recordRowsDir = "eval-tables"

// NewRecord validates an EvalTable that an offline run logs, and returns
// the record that `wandb sync` uploads it from.
//
// The record names the table and its first version, so that the run's
// history can reference them before the upload. NewRecord copies the
// table's W&B rows file, if it has one, into syncDir, because the client
// deletes it after the response.
//
// Errors in the table satisfy IsUsageError.
func NewRecord(
	data *spb.EvalTableData,
	runPath runbranch.RunPath,
	syncDir string,
) (*spb.EvalTableRecord, error) {
	table, err := Encode(data, runPath)
	if err != nil {
		return nil, err
	}
	if err := table.Close(); err != nil {
		return nil, err
	}

	record := &spb.EvalTableRecord{
		Table:               proto.CloneOf(data),
		EvaluationId:        table.ids.evaluationID,
		EvaluationVersionId: table.ids.evaluationVersionID,
	}

	if path := data.GetWandbRowsFilePath(); path != "" {
		record.Table.WandbRowsFilePath = ""
		record.WandbRowsFile = filepath.Join(
			recordRowsDir,
			table.ids.evaluationID+".wandb-rows.gz",
		)

		dst := filepath.Join(syncDir, record.WandbRowsFile)
		if err := fileutil.CopyFile(path, dst); err != nil {
			return nil, fmt.Errorf("evaltables: failed to copy W&B rows file: %v", err)
		}
	}

	return record, nil
}

// EncodeRecord validates and encodes an EvalTable from an offline run's
// record, keeping the IDs that the run's history references.
//
// The caller must Close the returned table.
func EncodeRecord(
	record *spb.EvalTableRecord,
	runPath runbranch.RunPath,
	syncDir string,
) (*EncodedTable, error) {
	data := record.GetTable()

	if file := record.GetWandbRowsFile(); file != "" {
		if !filepath.IsLocal(file) {
			return nil, fmt.Errorf(
				"evaltables: W&B rows file %q is outside the sync directory",
				file,
			)
		}
		data = proto.CloneOf(data)
		data.WandbRowsFilePath = filepath.Join(syncDir, file)
	}

	if record.GetEvaluationId() == "" || record.GetEvaluationVersionId() == "" {
		return nil, errors.New("evaltables: record has no evaluation ID or evaluation version ID")
	}

	table, err := Encode(data, runPath)
	if err != nil {
		return nil, err
	}
	table.ids = tableIDs{
		evaluationID:        record.GetEvaluationId(),
		evaluationVersionID: record.GetEvaluationVersionId(),
	}
	return table, nil
}
