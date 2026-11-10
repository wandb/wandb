package evaltables

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"iter"
	"os"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/google/uuid"
	"google.golang.org/protobuf/proto"

	ces "github.com/wandb/cwevals-go"
	"github.com/wandb/cwevals-go/option"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// maxRequestBodyBytes is CES's request body limit.
	maxRequestBodyBytes = 16 << 20

	// targetRowBatchBytes is the size above which a row append request body
	// is split, so we leave headroom below CES's 16 MiB request limit.
	targetRowBatchBytes = 8 << 20

	maxRowsPerBatch = 10_000

	// rowBatchPrefix and rowBatchSuffix enclose the rows in a row append
	// request body.
	rowBatchPrefix = `{"rows":[`
	rowBatchSuffix = `]}`

	idempotencyKeyVersion = "v3"
)

type Uploader struct {
	graphqlClient graphql.Client
	runHandle     *runhandle.RunHandle

	// evalTables returns the CES client, creating it on first use.
	evalTables func() (*ces.EvalTableService, error)

	// scopeMu guards scopeID.
	scopeMu sync.Mutex

	// scopeID is the run's project's internal ID, or empty if not yet fetched.
	scopeID string
}

type UploaderParams struct {
	CredentialProvider api.CredentialProvider
	GraphqlClient      graphql.Client
	Logger             *observability.CoreLogger
	RunHandle          *runhandle.RunHandle
	Settings           *settings.Settings
}

func NewUploader(params UploaderParams) *Uploader {
	return &Uploader{
		graphqlClient: params.GraphqlClient,
		runHandle:     params.RunHandle,
		evalTables: sync.OnceValues(func() (*ces.EvalTableService, error) {
			return NewEvalTableService(
				params.CredentialProvider,
				params.Logger.Logger,
				params.Settings,
			)
		}),
	}
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
	name    string
	runPath runbranch.RunPath
	columns ces.EvalTableColumnNewParams
	encoder *rowEncoder

	// rowsJSON is the CES JSON of the request's inline rows.
	rowsJSON [][]byte

	// rowsFilePath is the request's rows file, if any, which is encoded
	// while uploading.
	rowsFilePath string
}

// rows returns the table's CES row JSON.
func (t *EncodedTable) rows() iter.Seq2[[]byte, error] {
	if t.rowsFilePath != "" {
		return t.encoder.encodeRows(rowsFromFile(t.rowsFilePath))
	}

	return func(yield func([]byte, error) bool) {
		for _, row := range t.rowsJSON {
			if !yield(row, nil) {
				return
			}
		}
	}
}

// Encode validates an EvalTable upload request and encodes its rows.
//
// Errors in the request's table satisfy IsUsageError.
func (u *Uploader) Encode(
	request *spb.UploadEvalTableRequest,
) (*EncodedTable, error) {
	upserter, err := u.runHandle.Upserter()
	if err != nil {
		return nil, fmt.Errorf("evaltables: %v", err)
	}
	runPath := upserter.RunPath()

	columns := ces.EvalTableColumnNewParams{
		DatasetFields: ces.F(datasetFieldParams(request.GetDatasetFields())),
		Scorers:       ces.F(scorerParams(request.GetScorers())),
	}
	if err := validateColumns(request, &columns); err != nil {
		return nil, usageError{err}
	}

	table := &EncodedTable{
		name:         request.GetName(),
		runPath:      runPath,
		columns:      columns,
		encoder:      newRowEncoder(request, runPath),
		rowsFilePath: request.GetRowsFilePath(),
	}
	if table.rowsFilePath != "" {
		return table, nil
	}

	for rowJSON, err := range table.encoder.encodeRows(requestRows(request)) {
		if err != nil {
			return nil, usageError{err}
		}
		table.rowsJSON = append(table.rowsJSON, rowJSON)
	}

	return table, nil
}

// Upload creates an EvalTable in CES, adds its columns and rows,
// and cuts a version.
//
// It deletes the table's rows file, if any.
func (u *Uploader) Upload(
	ctx context.Context,
	table *EncodedTable,
) (*spb.UploadEvalTableResponse, error) {
	if table.rowsFilePath != "" {
		defer func() { _ = os.Remove(table.rowsFilePath) }()
	}

	evalTables, err := u.evalTables()
	if err != nil {
		return nil, err
	}

	scopeID, err := u.projectScopeID(ctx, table.runPath)
	if err != nil {
		return nil, err
	}
	scope := ces.F(scopeID)
	columns := table.columns
	columns.ScopeID = scope
	keys := newIdempotencyKeys()

	created, err := evalTables.New(
		ctx,
		ces.EvalTableNewParams{ScopeID: scope, Name: ces.F(table.name)},
		keys.option("create"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to create EvalTable: %v", err)
	}

	_, err = evalTables.Columns.New(
		ctx,
		created.EvaluationID,
		columns,
		keys.option("columns"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to add columns: %v", err)
	}

	// NewProgress only fails if the operation already has progress.
	progress, _ := wboperation.Get(ctx).NewProgress()
	totalRows := len(table.rowsJSON)
	rowsDone := 0
	batchIndex := 0
	for batch, err := range rowBatches(table.rows()) {
		if err != nil {
			return nil, err
		}

		if _, err := evalTables.Rows.Add(
			ctx,
			created.EvaluationID,
			ces.EvalTableRowAddParams{ScopeID: scope},
			keys.option(fmt.Sprintf("rows-%d", batchIndex)),
			// The rows are already JSON, so send them without decoding them
			// into the CES SDK's types.
			option.WithRequestBody("application/json", batch.body),
		); err != nil {
			return nil, fmt.Errorf("evaltables: failed to add rows: %v", err)
		}
		batchIndex++

		rowsDone += batch.rows
		if totalRows > 0 {
			progress.SetUnitsOfTotal(rowsDone, totalRows, "rows")
		} else {
			// A rows file's row count isn't known until it's read.
			progress.SetUnitsDone(rowsDone, "rows")
		}
	}

	version, err := evalTables.Versions.New(
		ctx,
		created.EvaluationID,
		ces.EvalTableVersionNewParams{ScopeID: scope},
		keys.option("version"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to cut version: %v", err)
	}

	return &spb.UploadEvalTableResponse{
		EvaluationId:        created.EvaluationID,
		EvaluationVersionId: version.EvaluationVersionID,
		DatasetId:           created.DatasetID,
		DatasetVersionId:    version.DatasetVersionID,
	}, nil
}

// projectScopeID returns the internal ID of the run's project.
func (u *Uploader) projectScopeID(
	ctx context.Context,
	runPath runbranch.RunPath,
) (string, error) {
	u.scopeMu.Lock()
	scopeID := u.scopeID
	u.scopeMu.Unlock()

	if scopeID != "" {
		return scopeID, nil
	}

	// Concurrent uploads may look up the ID more than once; that's harmless.
	response, err := gql.ProjectInternalID(
		ctx,
		u.graphqlClient,
		runPath.Entity,
		runPath.Project,
	)
	if err != nil {
		return "", fmt.Errorf("evaltables: failed to look up project: %v", err)
	}

	project := response.GetProject()
	if project == nil || project.GetInternalId() == "" {
		return "", fmt.Errorf(
			"evaltables: project %s/%s not found",
			runPath.Entity,
			runPath.Project,
		)
	}

	scopeID = project.GetInternalId()

	u.scopeMu.Lock()
	u.scopeID = scopeID
	u.scopeMu.Unlock()

	return scopeID, nil
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

// requestRows returns the request's rows.
func requestRows(
	request *spb.UploadEvalTableRequest,
) iter.Seq2[*spb.EvalTableRow, error] {
	if path := request.GetRowsFilePath(); path != "" {
		return rowsFromFile(path)
	}

	return func(yield func(*spb.EvalTableRow, error) bool) {
		for _, row := range request.GetRows() {
			if !yield(row, nil) {
				return
			}
		}
	}
}

// maxRowFileMessageBytes limits the size of a row in a rows file.
//
// A row's proto encoding can be larger than its CES JSON, such as for many
// small numbers, so this allows rows well above CES's request limit and
// leaves the exact check to rowEncoder.
const maxRowFileMessageBytes = 4 * maxRequestBodyBytes

// rowsFromFile returns the rows in a gzipped file of EvalTableRow messages,
// each preceded by its size as a varint.
func rowsFromFile(path string) iter.Seq2[*spb.EvalTableRow, error] {
	return func(yield func(*spb.EvalTableRow, error) bool) {
		file, err := os.Open(path)
		if err != nil {
			yield(nil, fmt.Errorf("evaltables: failed to read rows: %v", err))
			return
		}
		defer func() { _ = file.Close() }()

		gzReader, err := gzip.NewReader(file)
		if err != nil {
			yield(nil, fmt.Errorf("evaltables: failed to read rows: %v", err))
			return
		}
		defer func() { _ = gzReader.Close() }()

		reader := bufio.NewReader(gzReader)
		for {
			row, err := readRow(reader)
			switch {
			case errors.Is(err, io.EOF):
				return
			case err != nil:
				yield(nil, fmt.Errorf("evaltables: failed to read rows: %v", err))
				return
			case !yield(row, nil):
				return
			}
		}
	}
}

// readRow reads a varint-delimited EvalTableRow, or returns io.EOF at the
// end of the file.
func readRow(reader *bufio.Reader) (*spb.EvalTableRow, error) {
	size, err := binary.ReadUvarint(reader)
	if err != nil {
		return nil, err
	}
	if size > maxRowFileMessageBytes {
		return nil, fmt.Errorf(
			"row is %d bytes, must be at most %d", size, maxRowFileMessageBytes)
	}

	message := make([]byte, size)
	if _, err := io.ReadFull(reader, message); err != nil {
		return nil, fmt.Errorf("truncated row: %v", err)
	}

	row := &spb.EvalTableRow{}
	if err := proto.Unmarshal(message, row); err != nil {
		return nil, err
	}
	return row, nil
}

// validateColumns checks that the request's columns have known types,
// which the CES SDK doesn't check, and that their CES request fits
// CES's size limit.
func validateColumns(
	request *spb.UploadEvalTableRequest,
	columns *ces.EvalTableColumnNewParams,
) error {
	for _, field := range request.GetDatasetFields() {
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
		}
	}

	for _, scorer := range request.GetScorers() {
		valueType := ces.EvalTableColumnNewParamsScorersValueType(scorer.GetValueType())
		if !valueType.IsKnown() {
			return fmt.Errorf(
				"scorer %q has unknown value type %q",
				scorer.GetName(), valueType)
		}
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

type rowBatch struct {
	body []byte
	rows int
}

// rowBatches groups JSON-encoded rows into row append request bodies.
//
// Each body has at most maxRowsPerBatch rows and is at most
// targetRowBatchBytes, unless it has a single larger row.
// It stops after the first error from rows.
func rowBatches(rows iter.Seq2[[]byte, error]) iter.Seq2[rowBatch, error] {
	return func(yield func(rowBatch, error) bool) {
		var body bytes.Buffer
		nrows := 0

		flush := func() bool {
			body.WriteString(rowBatchSuffix)
			batch := rowBatch{body: bytes.Clone(body.Bytes()), rows: nrows}
			body.Reset()
			nrows = 0
			return yield(batch, nil)
		}

		for row, err := range rows {
			if err != nil {
				yield(rowBatch{}, err)
				return
			}

			if nrows > 0 &&
				(nrows >= maxRowsPerBatch ||
					body.Len()+1+len(row)+len(rowBatchSuffix) > targetRowBatchBytes) {
				if !flush() {
					return
				}
			}

			if nrows == 0 {
				body.WriteString(rowBatchPrefix)
			} else {
				body.WriteByte(',')
			}
			body.Write(row)
			nrows++
		}

		if nrows > 0 {
			flush()
		}
	}
}

type idempotencyKeys struct {
	prefix string
}

// newIdempotencyKeys derives CES idempotency keys for one EvalTable upload.
//
// The keys share a random ID, so that retries within the upload reuse the
// CES resources it already created, and separate uploads never collide.
// Uploads can't key on where the table is logged: in shared mode, writers
// to the same run can log the same key at the same step.
//
// CES replays a request with the same key and body, and rejects one with
// the same key but a different body.
func newIdempotencyKeys() idempotencyKeys {
	return idempotencyKeys{
		prefix: fmt.Sprintf(
			"wandb-eval-table-%s-%s",
			idempotencyKeyVersion,
			uuid.Must(uuid.NewV7()),
		),
	}
}

// option returns a request option setting the key for an operation.
func (k idempotencyKeys) option(operation string) option.RequestOption {
	return option.WithHeader("Idempotency-Key", k.prefix+"-"+operation)
}
