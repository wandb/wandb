package evaltables

import (
	"errors"
	"fmt"

	ces "github.com/wandb/cwevals-go"

	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runhandle"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// maxRequestBodyBytes is CES's request body limit.
	maxRequestBodyBytes = 16 << 20

	rowBatchPrefix = `{"rows":[`
	rowBatchSuffix = `]}`
)

type Uploader struct {
	runHandle *runhandle.RunHandle
}

type UploaderParams struct {
	RunHandle *runhandle.RunHandle
}

func NewUploader(params UploaderParams) *Uploader {
	return &Uploader{runHandle: params.RunHandle}
}

// usageError is a problem with a request's table, which the user can fix.
type usageError struct{ error }

// IsUsageError reports whether err is a problem with the table in an
// upload request, rather than a failure to upload it.
func IsUsageError(err error) bool {
	return errors.As(err, &usageError{})
}

// EncodedTable is an EvalTable that has been validated and encoded for
// CES.
type EncodedTable struct {
	name     string
	runPath  runbranch.RunPath
	columns  ces.EvalTableColumnNewParams
	rowsJSON [][]byte
}

// Encode validates an EvalTable and encodes its rows.
//
// Errors in the table satisfy IsUsageError.
func (u *Uploader) Encode(
	data *spb.EvalTableData,
) (*EncodedTable, error) {
	upserter, err := u.runHandle.Upserter()
	if err != nil {
		return nil, fmt.Errorf("evaltables: %v", err)
	}
	runPath := upserter.RunPath()

	columns := ces.EvalTableColumnNewParams{
		DatasetFields: ces.F(datasetFieldParams(data.GetDatasetFields())),
		Scorers:       ces.F(scorerParams(data.GetScorers())),
	}
	if err := validateColumns(data, &columns); err != nil {
		return nil, usageError{err}
	}

	encoder, err := newRowEncoder(data, runPath)
	if err != nil {
		return nil, usageError{err}
	}
	rowsJSON, err := encoder.encodeRows(data.GetRows())
	if err != nil {
		return nil, usageError{err}
	}

	return &EncodedTable{
		name:     data.GetName(),
		runPath:  runPath,
		columns:  columns,
		rowsJSON: rowsJSON,
	}, nil
}

func datasetFieldParams(
	fields []*spb.EvalTableField,
) []ces.EvalTableColumnNewParamsDatasetField {
	params := make([]ces.EvalTableColumnNewParamsDatasetField, len(fields))

	for i, field := range fields {
		params[i] = ces.EvalTableColumnNewParamsDatasetField{
			Name: ces.F(field.GetName()),
			Source: ces.F(
				ces.EvalTableColumnNewParamsDatasetFieldsSource(field.GetSource())),
			ValueType: ces.F(
				ces.EvalTableColumnNewParamsDatasetFieldsValueType(field.GetValueType())),
		}

		if extensionType, ok := mediaExtensionTypes[field.GetWandbMediaType()]; ok {
			params[i].ExtensionType = ces.F(extensionType)
			params[i].ExtensionSchemaVersion = ces.F(int64(mediaSchemaVersion))
		}
	}

	return params
}

func scorerParams(scorers []*spb.EvalTableScorer) []ces.EvalTableColumnNewParamsScorer {
	params := make([]ces.EvalTableColumnNewParamsScorer, len(scorers))

	for i, scorer := range scorers {
		params[i] = ces.EvalTableColumnNewParamsScorer{
			Name: ces.F(scorer.GetName()),
			ValueType: ces.F(
				ces.EvalTableColumnNewParamsScorersValueType(scorer.GetValueType())),
		}
	}

	return params
}

// validateColumns checks that the table's columns have known types and
// unique names, and that their CES request fits CES's size limit, so that
// an invalid table fails before any CES request.
func validateColumns(
	data *spb.EvalTableData,
	columns *ces.EvalTableColumnNewParams,
) error {
	type fieldKey struct{ source, name string }
	fields := make(map[fieldKey]bool)
	for _, field := range data.GetDatasetFields() {
		key := fieldKey{field.GetSource(), field.GetName()}
		source := ces.EvalTableColumnNewParamsDatasetFieldsSource(field.GetSource())
		valueType := ces.EvalTableColumnNewParamsDatasetFieldsValueType(field.GetValueType())
		mediaType := field.GetWandbMediaType()
		_, isKnownMediaType := mediaExtensionTypes[mediaType]

		switch {
		case !source.IsKnown():
			return fmt.Errorf(
				"field %q has unknown source %q",
				field.GetName(), source)
		case !valueType.IsKnown():
			return fmt.Errorf(
				"field %q has unknown value type %q",
				field.GetName(), valueType)
		case mediaType != "" && !isKnownMediaType:
			return fmt.Errorf(
				"field %q has unknown media type %q",
				field.GetName(), mediaType)
		case fields[key]:
			return fmt.Errorf("duplicate %s field %q", source, field.GetName())
		}
		fields[key] = true
	}

	scorers := make(map[string]bool)
	for _, scorer := range data.GetScorers() {
		valueType := ces.EvalTableColumnNewParamsScorersValueType(scorer.GetValueType())
		switch {
		case !valueType.IsKnown():
			return fmt.Errorf(
				"scorer %q has unknown value type %q",
				scorer.GetName(), valueType)
		case scorers[scorer.GetName()]:
			return fmt.Errorf("duplicate scorer %q", scorer.GetName())
		}
		scorers[scorer.GetName()] = true
	}

	body, err := columns.MarshalJSON()
	if err != nil {
		return fmt.Errorf("failed to encode columns: %v", err)
	}
	if len(body) >= maxRequestBodyBytes {
		return fmt.Errorf(
			"columns request is %d bytes, must be under %d",
			len(body), maxRequestBodyBytes)
	}

	return nil
}
