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
	"path/filepath"
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

	// Row append requests carry about 1/rowBatchesPerTable of the table,
	// so that the upload reports progress in steps, but at least
	// minRowsPerBatch rows to limit CES commits. maxRowsPerBatch is CES's
	// limit.
	rowBatchesPerTable = 10
	minRowsPerBatch    = 1_000
	maxRowsPerBatch    = 10_000

	rowBatchPrefix = `{"rows":[`
	rowBatchSuffix = `]}`

	idempotencyKeyVersion = "v3"
)

type Uploader struct {
	graphqlClient graphql.Client
	logger        *observability.CoreLogger

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
	Settings           *settings.Settings
}

func NewUploader(params UploaderParams) *Uploader {
	return &Uploader{
		graphqlClient: params.GraphqlClient,
		logger:        params.Logger,
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
	nrows   int

	// cesRows is the CES JSON of the table's inline rows.
	cesRows [][]byte

	// cesRowsPath is the CES rows file: a temporary file of the CES JSON of
	// the table's W&B rows file, if it has one, so that Upload neither holds
	// those rows' JSON in memory nor encodes them again.
	cesRowsPath string
}

func (t *EncodedTable) rows() iter.Seq2[[]byte, error] {
	if t.cesRowsPath != "" {
		return cesRowsFromFile(t.cesRowsPath)
	}

	return func(yield func([]byte, error) bool) {
		for _, row := range t.cesRows {
			if !yield(row, nil) {
				return
			}
		}
	}
}

// Close removes the table's CES rows file, if it has one.
func (t *EncodedTable) Close() error {
	if t.cesRowsPath == "" {
		return nil
	}
	if err := os.Remove(t.cesRowsPath); err != nil {
		return fmt.Errorf("evaltables: failed to remove CES rows file: %v", err)
	}
	return nil
}

// Encode validates an EvalTable of the run at runPath and encodes its rows.
//
// It encodes every row, so that an invalid table fails before Upload
// writes anything to CES. The caller must Close the returned table.
//
// Errors in the table satisfy IsUsageError. Cancelling ctx stops reading a
// W&B rows file.
func Encode(
	ctx context.Context,
	data *spb.EvalTableData,
	runPath runbranch.RunPath,
) (*EncodedTable, error) {
	if len(data.GetRows()) > 0 && data.GetWandbRowsFilePath() != "" {
		return nil, errors.New("evaltables: request has both rows and a W&B rows file")
	}

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

	table := &EncodedTable{
		name:    data.GetName(),
		runPath: runPath,
		columns: columns,
	}

	if path := data.GetWandbRowsFilePath(); path != "" {
		if err := table.writeCESRowsFile(ctx, encoder, path); err != nil {
			return nil, err
		}
		return table, nil
	}

	for rowJSON, err := range encoder.encodeRows(inlineRows(data)) {
		if err != nil {
			return nil, err
		}
		table.nrows++
		table.cesRows = append(table.cesRows, rowJSON)
	}
	return table, nil
}

// writeCESRowsFile encodes the rows in a W&B rows file into a CES rows file
// next to it, one row's CES JSON per line.
//
// CES row JSON is compact, so it never contains a newline.
func (t *EncodedTable) writeCESRowsFile(
	ctx context.Context,
	encoder *rowEncoder,
	wandbRowsPath string,
) (err error) {
	file, err := os.CreateTemp(
		filepath.Dir(wandbRowsPath), "wandb-eval-table-*.ces-rows.jsonl")
	if err != nil {
		return fmt.Errorf("evaltables: failed to create CES rows file: %v", err)
	}
	t.cesRowsPath = file.Name()
	defer func() {
		if closeErr := file.Close(); err == nil && closeErr != nil {
			err = fmt.Errorf("evaltables: failed to write CES rows file: %v", closeErr)
		}
		if err != nil {
			err = errors.Join(err, t.Close())
		}
	}()

	writer := bufio.NewWriter(file)
	for rowJSON, err := range encoder.encodeRows(wandbRowsFromFile(ctx, wandbRowsPath)) {
		if err != nil {
			return err
		}
		t.nrows++
		if _, err := writer.Write(rowJSON); err != nil {
			return fmt.Errorf("evaltables: failed to write CES rows file: %v", err)
		}
		if err := writer.WriteByte('\n'); err != nil {
			return fmt.Errorf("evaltables: failed to write CES rows file: %v", err)
		}
	}
	if err := writer.Flush(); err != nil {
		return fmt.Errorf("evaltables: failed to write CES rows file: %v", err)
	}
	return nil
}

// cesRowsFromFile returns the rows in a CES rows file.
func cesRowsFromFile(path string) iter.Seq2[[]byte, error] {
	return func(yield func([]byte, error) bool) {
		file, err := os.Open(path)
		if err != nil {
			yield(nil, fmt.Errorf("evaltables: failed to read CES rows file: %v", err))
			return
		}
		defer func() { _ = file.Close() }()

		reader := bufio.NewReader(file)
		for {
			row, err := readCESRow(reader)
			if errors.Is(err, io.EOF) {
				return
			}
			if err != nil {
				yield(nil, fmt.Errorf("evaltables: failed to read CES rows file: %v", err))
				return
			}
			if !yield(row, nil) {
				return
			}
		}
	}
}

// readCESRow reads one row from a CES rows file.
//
// It returns io.EOF only at the end of the file, between rows.
func readCESRow(reader *bufio.Reader) ([]byte, error) {
	line, err := reader.ReadBytes('\n')
	switch {
	case errors.Is(err, io.EOF) && len(line) > 0:
		return nil, io.ErrUnexpectedEOF
	case err != nil:
		return nil, err
	}
	return line[:len(line)-1], nil
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

	upload := &tableUpload{
		evalTables: evalTables,
		scopeID:    scopeID,
		keys:       newIdempotencyKeys(),
	}

	created, err := upload.create(ctx, table)
	if err != nil {
		return nil, err
	}
	if err := upload.addRows(ctx, table, u.newProgress(ctx)); err != nil {
		return nil, err
	}
	version, err := upload.cutVersion(ctx)
	if err != nil {
		return nil, err
	}

	return &spb.UploadEvalTableResponse{
		EvaluationId:        created.EvaluationID,
		EvaluationVersionId: version.EvaluationVersionID,
		DatasetId:           created.DatasetID,
		DatasetVersionId:    version.DatasetVersionID,
	}, nil
}

// newProgress returns the progress of the upload's operation, or nil if
// it can't, in which case the upload reports no progress.
func (u *Uploader) newProgress(ctx context.Context) *wboperation.WandbProgress {
	progress, err := wboperation.Get(ctx).NewProgress()
	if err != nil {
		u.logger.CaptureError("evaltables", fmt.Errorf("evaltables: %v", err))
	}
	return progress
}

// tableUpload makes the CES requests of one Upload.
type tableUpload struct {
	evalTables *ces.EvalTableService
	scopeID    string
	keys       idempotencyKeys

	// evaluationID is the created EvalTable's ID, set by create.
	evaluationID string
}

// create creates the EvalTable in CES and adds its columns.
func (t *tableUpload) create(
	ctx context.Context,
	table *EncodedTable,
) (*ces.EvalTableNewResponse, error) {
	created, err := t.evalTables.New(
		ctx,
		ces.EvalTableNewParams{ScopeID: ces.F(t.scopeID), Name: ces.F(table.name)},
		t.keys.option("create"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to create EvalTable: %v", err)
	}
	t.evaluationID = created.EvaluationID

	columns := table.columns
	columns.ScopeID = ces.F(t.scopeID)
	_, err = t.evalTables.Columns.New(
		ctx,
		t.evaluationID,
		columns,
		t.keys.option("columns"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to add columns: %v", err)
	}

	return created, nil
}

// addRows adds the table's rows in batches, reporting them to progress.
func (t *tableUpload) addRows(
	ctx context.Context,
	table *EncodedTable,
	progress *wboperation.WandbProgress,
) error {
	rowsDone := 0
	batchIndex := 0
	for batch, err := range rowBatches(table.rows(), rowsPerBatch(table.nrows)) {
		if err != nil {
			return err
		}

		if _, err := t.evalTables.Rows.Add(
			ctx,
			t.evaluationID,
			ces.EvalTableRowAddParams{ScopeID: ces.F(t.scopeID)},
			t.keys.option(fmt.Sprintf("rows-%d", batchIndex)),
			// The rows are already JSON, so send them without decoding them
			// into the CES SDK's types.
			option.WithRequestBody("application/json", batch.body),
		); err != nil {
			return fmt.Errorf("evaltables: failed to add rows: %v", err)
		}
		batchIndex++

		rowsDone += batch.rows
		progress.SetUnitsOfTotal(rowsDone, table.nrows, "rows")
	}
	return nil
}

func (t *tableUpload) cutVersion(
	ctx context.Context,
) (*ces.EvalTableVersionNewResponse, error) {
	version, err := t.evalTables.Versions.New(
		ctx,
		t.evaluationID,
		ces.EvalTableVersionNewParams{ScopeID: ces.F(t.scopeID)},
		t.keys.option("version"),
	)
	if err != nil {
		return nil, fmt.Errorf("evaltables: failed to cut version: %v", err)
	}
	return version, nil
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

func inlineRows(
	data *spb.EvalTableData,
) iter.Seq2[*spb.EvalTableRow, error] {
	return func(yield func(*spb.EvalTableRow, error) bool) {
		for _, row := range data.GetRows() {
			if !yield(row, nil) {
				return
			}
		}
	}
}

// maxWandbRowBytes limits the size of a row in a W&B rows file.
//
// A row's proto encoding can be larger than its CES JSON, such as for many
// small numbers, so this allows rows well above CES's request limit and
// leaves the exact check to rowEncoder.
const maxWandbRowBytes = 4 * maxRequestBodyBytes

// wandbRowsFromFile returns the rows in a W&B rows file: a gzipped file of
// EvalTableRow messages, each preceded by its size as a varint.
func wandbRowsFromFile(
	ctx context.Context,
	path string,
) iter.Seq2[*spb.EvalTableRow, error] {
	return func(yield func(*spb.EvalTableRow, error) bool) {
		file, err := os.Open(path)
		if err != nil {
			yield(nil, fmt.Errorf("evaltables: failed to read W&B rows file: %v", err))
			return
		}
		defer func() { _ = file.Close() }()

		gzReader, err := gzip.NewReader(file)
		if err != nil {
			yield(nil, fmt.Errorf("evaltables: failed to read W&B rows file: %v", err))
			return
		}
		defer func() { _ = gzReader.Close() }()

		reader := bufio.NewReader(gzReader)
		for {
			if err := ctx.Err(); err != nil {
				yield(nil, err)
				return
			}

			row, err := readWandbRow(reader)
			switch {
			case errors.Is(err, io.EOF):
				return
			case err != nil:
				yield(nil, fmt.Errorf("evaltables: failed to read W&B rows file: %v", err))
				return
			case !yield(row, nil):
				return
			}
		}
	}
}

// readWandbRow reads a varint-delimited EvalTableRow, or returns io.EOF at the
// end of the file.
func readWandbRow(reader *bufio.Reader) (*spb.EvalTableRow, error) {
	size, err := binary.ReadUvarint(reader)
	if err != nil {
		return nil, err
	}
	if size > maxWandbRowBytes {
		return nil, fmt.Errorf(
			"row is %d bytes, must be at most %d", size, maxWandbRowBytes)
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

type rowBatch struct {
	body []byte
	rows int
}

// rowsPerBatch is the most rows to send per row append request of a table
// with nrows rows.
func rowsPerBatch(nrows int) int {
	perBatch := (nrows + rowBatchesPerTable - 1) / rowBatchesPerTable
	return min(max(perBatch, minRowsPerBatch), maxRowsPerBatch)
}

// rowBatches groups JSON-encoded rows into row append request bodies.
//
// Each body has at most maxRows rows and is at most targetRowBatchBytes,
// unless it has a single larger row.
// It stops after the first error from rows.
func rowBatches(
	rows iter.Seq2[[]byte, error],
	maxRows int,
) iter.Seq2[rowBatch, error] {
	return func(yield func(rowBatch, error) bool) {
		batch := rowBatchBuilder{maxRows: maxRows}

		for row, err := range rows {
			if err != nil {
				yield(rowBatch{}, err)
				return
			}

			if !batch.fits(row) && !yield(batch.take(), nil) {
				return
			}
			batch.add(row)
		}

		if batch.nrows > 0 {
			yield(batch.take(), nil)
		}
	}
}

type rowBatchBuilder struct {
	body    bytes.Buffer
	nrows   int
	maxRows int
}

// Any row fits in an empty batch.
func (b *rowBatchBuilder) fits(row []byte) bool {
	return b.nrows == 0 ||
		(b.nrows < b.maxRows &&
			b.body.Len()+1+len(row)+len(rowBatchSuffix) <= targetRowBatchBytes)
}

func (b *rowBatchBuilder) add(row []byte) {
	if b.nrows == 0 {
		b.body.WriteString(rowBatchPrefix)
	} else {
		b.body.WriteByte(',')
	}
	b.body.Write(row)
	b.nrows++
}

func (b *rowBatchBuilder) take() rowBatch {
	b.body.WriteString(rowBatchSuffix)
	batch := rowBatch{body: bytes.Clone(b.body.Bytes()), rows: b.nrows}
	b.body.Reset()
	b.nrows = 0
	return batch
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
// CES replays a create, row append, or version request with the same key,
// and rejects one with the same key but a different body. Repeating an
// identical column declaration is a no-op.
func newIdempotencyKeys() idempotencyKeys {
	return idempotencyKeys{
		prefix: fmt.Sprintf(
			"wandb-eval-table-%s-%s",
			idempotencyKeyVersion,
			uuid.Must(uuid.NewV7()),
		),
	}
}

func (k idempotencyKeys) option(operation string) option.RequestOption {
	return option.WithHeader("Idempotency-Key", k.prefix+"-"+operation)
}
