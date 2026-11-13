package evaltables

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/google/uuid"

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
	name     string
	runPath  runbranch.RunPath
	columns  ces.EvalTableColumnNewParams
	rowsJSON [][]byte
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

	encoder, err := newRowEncoder(request, runPath)
	if err != nil {
		return nil, usageError{err}
	}
	rowsJSON, err := encoder.encodeRows(request.GetRows())
	if err != nil {
		return nil, usageError{err}
	}

	return &EncodedTable{
		name:     request.GetName(),
		runPath:  runPath,
		columns:  columns,
		rowsJSON: rowsJSON,
	}, nil
}

// Upload creates an EvalTable in CES, adds its columns and rows,
// and cuts a version.
func (u *Uploader) Upload(
	ctx context.Context,
	table *EncodedTable,
) (*spb.UploadEvalTableResponse, error) {
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
	for i, batch := range rowBatches(table.rowsJSON) {
		_, err = evalTables.Rows.Add(
			ctx,
			created.EvaluationID,
			ces.EvalTableRowAddParams{ScopeID: scope},
			keys.option(fmt.Sprintf("rows-%d", i)),
			// The rows are already JSON, so send them without decoding them
			// into the CES SDK's types.
			option.WithRequestBody("application/json", batch.body),
		)
		if err != nil {
			return nil, fmt.Errorf("evaltables: failed to add rows: %v", err)
		}

		rowsDone += batch.rows
		progress.SetUnitsOfTotal(rowsDone, totalRows, "rows")
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

// validateColumns checks that the request's columns have known types and
// that their CES request fits CES's size limit, so that an invalid table
// fails before any CES request.
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
func rowBatches(rowsJSON [][]byte) []rowBatch {
	var batches []rowBatch
	var body bytes.Buffer
	nrows := 0

	flush := func() {
		body.WriteString(rowBatchSuffix)
		batches = append(batches, rowBatch{
			body: bytes.Clone(body.Bytes()),
			rows: nrows,
		})
		body.Reset()
		nrows = 0
	}

	for _, row := range rowsJSON {
		if nrows > 0 &&
			(nrows >= maxRowsPerBatch ||
				body.Len()+1+len(row)+len(rowBatchSuffix) > targetRowBatchBytes) {
			flush()
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

	return batches
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
