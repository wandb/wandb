package evaltables_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/evaltables"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const tablePath = "/evaluations/v1/namespaces/wandb/scopes/project-internal-id/eval-tables"

type cesRequest struct {
	Path           string
	IdempotencyKey string
	Body           string
}

// fakeCES is a CES server that records requests and returns fixed IDs.
type fakeCES struct {
	*httptest.Server

	mu       sync.Mutex
	requests []cesRequest

	// onRequest, if set, is called with each request's path before
	// responding.
	onRequest func(path string)

	// errorStatus, if set, returns an HTTP status to fail a request with,
	// or 0 to respond normally.
	errorStatus func(path string) int
}

func newFakeCES(t *testing.T) *fakeCES {
	t.Helper()
	ces := &fakeCES{}

	ces.Server = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			body, err := io.ReadAll(r.Body)
			require.NoError(t, err)

			ces.mu.Lock()
			ces.requests = append(ces.requests, cesRequest{
				Path:           r.URL.Path,
				IdempotencyKey: r.Header.Get("Idempotency-Key"),
				Body:           string(body),
			})
			ces.mu.Unlock()

			if ces.onRequest != nil {
				ces.onRequest(r.URL.Path)
			}
			if ces.errorStatus != nil {
				if status := ces.errorStatus(r.URL.Path); status != 0 {
					w.WriteHeader(status)
					return
				}
			}

			w.Header().Set("Content-Type", "application/json")
			switch {
			case r.URL.Path == tablePath:
				_, _ = w.Write([]byte(`{
					"evaluation_id": "eval-id",
					"dataset_id": "dataset-id"
				}`))
			case strings.HasSuffix(r.URL.Path, "/versions"):
				_, _ = w.Write([]byte(`{
					"evaluation_version_id": "eval-version-id",
					"dataset_version_id": "dataset-version-id"
				}`))
			default:
				_, _ = w.Write([]byte(`{}`))
			}
		}))
	t.Cleanup(ces.Close)

	return ces
}

func (c *fakeCES) Requests() []cesRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.requests
}

const projectFoundJSON = `{"project": {"internalId": "project-internal-id"}}`

// newTestUploader returns an Uploader for a run in test-entity/test-project
// that uploads to ces.
//
// projectJSON is the response to the project's internal ID lookup.
func newTestUploader(
	t *testing.T,
	ces *fakeCES,
	projectJSON string,
) (*evaltables.Uploader, *gqlmock.MockClient) {
	t.Helper()
	return newTestUploaderWithSettings(t, projectJSON, settings.From(&spb.Settings{
		XCesBaseUrl: wrapperspb.String(ces.URL + "/evaluations"),
	}))
}

func newTestUploaderWithSettings(
	t *testing.T,
	projectJSON string,
	s *settings.Settings,
) (*evaltables.Uploader, *gqlmock.MockClient) {
	t.Helper()

	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(gqlmock.WithOpName("ProjectInternalID"), projectJSON)

	runHandle := runhandle.New()
	require.NoError(t, runHandle.Init(runupsertertest.NewOfflineUpserter(t)))

	return evaltables.NewUploader(evaltables.UploaderParams{
		CredentialProvider: api.NewAPIKeyCredentialProvider("test-api-key"),
		GraphqlClient:      mockGQL,
		Logger:             observabilitytest.NewTestLogger(t),
		RunHandle:          runHandle,
		Settings:           s,
	}), mockGQL
}

// upload encodes and uploads an EvalTable.
func upload(
	ctx context.Context,
	uploader *evaltables.Uploader,
	request *spb.UploadEvalTableRequest,
) (*spb.UploadEvalTableResponse, error) {
	table, err := uploader.Encode(request)
	if err != nil {
		return nil, err
	}
	return uploader.Upload(ctx, table)
}

// encode validates and encodes an EvalTable without uploading it.
func encode(
	t *testing.T,
	request *spb.UploadEvalTableRequest,
) (*evaltables.EncodedTable, error) {
	t.Helper()
	uploader, _ := newTestUploaderWithSettings(
		t, projectFoundJSON, settings.From(&spb.Settings{}))
	return uploader.Encode(request)
}

func boolValue(v bool) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_BoolValue{BoolValue: v}}
}

func intValue(v int64) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_IntValue{IntValue: v}}
}

func numberValue(v float64) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_NumberValue{NumberValue: v}}
}

func stringValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_StringValue{StringValue: v}}
}

func jsonValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_JsonValue{JsonValue: v}}
}

func mediaValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{
		Value: &spb.EvalTableValue_WandbMediaJson{WandbMediaJson: v},
	}
}

// nullValue returns an unset value, which is null.
func nullValue() *spb.EvalTableValue {
	return &spb.EvalTableValue{}
}

func values(v ...*spb.EvalTableValue) *spb.EvalTableRowValues {
	return &spb.EvalTableRowValues{Values: v}
}

// outputRows returns n rows whose only value is a string output "x" of
// the given length, keyed by position.
func outputRows(n, length int) []*spb.EvalTableRow {
	rows := make([]*spb.EvalTableRow, n)
	for i := range rows {
		rows[i] = &spb.EvalTableRow{
			Output:     values(stringValue(strings.Repeat("a", length))),
			ExampleKey: fmt.Sprint(i + 1),
		}
	}
	return rows
}

var outputFieldX = []*spb.EvalTableField{
	{Source: "output", Name: "x", ValueType: "string"},
}

func TestUpload(t *testing.T) {
	ces := newFakeCES(t)
	uploader, mockGQL := newTestUploader(t, ces, projectFoundJSON)

	response, err := upload(context.Background(), uploader, &spb.UploadEvalTableRequest{
		Name: "my-table",
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "prompt", ValueType: "string"},
			{Source: "output", Name: "answer", ValueType: "string"},
		},
		Scorers: []*spb.EvalTableScorer{{Name: "accuracy", ValueType: "number"}},
		Rows: []*spb.EvalTableRow{
			{
				Input:  values(stringValue("a")),
				Output: values(stringValue("x")),
				Scores: []*spb.EvalTableValue{numberValue(1)},
			},
			{
				Input:  values(stringValue("b")),
				Output: values(stringValue("y")),
				Scores: []*spb.EvalTableValue{numberValue(0)},
			},
		},
	})

	require.NoError(t, err)
	assert.Equal(t, &spb.UploadEvalTableResponse{
		EvaluationId:        "eval-id",
		EvaluationVersionId: "eval-version-id",
		DatasetId:           "dataset-id",
		DatasetVersionId:    "dataset-version-id",
	}, response)
	gqlmock.AssertVariables(t, mockGQL.AllRequests()[0],
		gqlmock.GQLVar("entityName", gomock.Eq("test-entity")),
		gqlmock.GQLVar("projectName", gomock.Eq("test-project")))

	requests := ces.Requests()
	require.Len(t, requests, 4)
	assert.Equal(t, tablePath, requests[0].Path)
	assert.JSONEq(t, `{"name": "my-table"}`, requests[0].Body)
	assert.Equal(t, tablePath+"/eval-id/columns", requests[1].Path)
	assert.JSONEq(t, `{
		"dataset_fields": [
			{"source": "input", "name": "prompt", "value_type": "string"},
			{"source": "output", "name": "answer", "value_type": "string"}
		],
		"scorers": [{"name": "accuracy", "value_type": "number"}]
	}`, requests[1].Body)
	assert.Equal(t, tablePath+"/eval-id/rows", requests[2].Path)
	assert.JSONEq(t, `{"rows": [
		{"input": {"prompt": "a"}, "output": {"answer": "x"}, "scores": {"accuracy": 1}},
		{"input": {"prompt": "b"}, "output": {"answer": "y"}, "scores": {"accuracy": 0}}
	]}`, requests[2].Body)
	assert.Equal(t, tablePath+"/eval-id/versions", requests[3].Path)
}

func TestEncode_AllValueTypes(t *testing.T) {
	table, err := encode(t, &spb.UploadEvalTableRequest{
		Name: "my-table",
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "flag", ValueType: "boolean"},
			{Source: "input", Name: "count", ValueType: "integer"},
			{Source: "input", Name: "temperature", ValueType: "number"},
			{Source: "input", Name: "prompt", ValueType: "string"},
			{Source: "input", Name: "config", ValueType: "json"},
			{Source: "input", Name: "note", ValueType: "string"},
			{Source: "output", Name: "answer", ValueType: "string"},
		},
		Scorers: []*spb.EvalTableScorer{
			{Name: "passed", ValueType: "boolean"},
			{Name: "votes", ValueType: "integer"},
			{Name: "accuracy", ValueType: "number"},
			{Name: "rank", ValueType: "number"},
			{Name: "grade", ValueType: "string"},
		},
		Rows: []*spb.EvalTableRow{
			{
				Input: values(
					boolValue(true),
					intValue(9007199254740993),
					numberValue(0.25),
					stringValue("draw <a> cat & dog"),
					jsonValue(`{"seed":7,"tags":["a","b"]}`),
					nullValue(),
				),
				Output: values(stringValue("a cat")),
				Scores: []*spb.EvalTableValue{
					boolValue(false),
					intValue(3),
					numberValue(0.5),
					intValue(2),
					stringValue("B"),
				},
			},
			{
				Scores: []*spb.EvalTableValue{
					nullValue(), nullValue(), nullValue(), nullValue(), nullValue(),
				},
				ExampleKey: "2",
			},
		},
	})

	require.NoError(t, err)
	assert.JSONEq(t, `{
		"dataset_fields": [
			{"source": "input", "name": "flag", "value_type": "boolean"},
			{"source": "input", "name": "count", "value_type": "integer"},
			{"source": "input", "name": "temperature", "value_type": "number"},
			{"source": "input", "name": "prompt", "value_type": "string"},
			{"source": "input", "name": "config", "value_type": "json"},
			{"source": "input", "name": "note", "value_type": "string"},
			{"source": "output", "name": "answer", "value_type": "string"}
		],
		"scorers": [
			{"name": "passed", "value_type": "boolean"},
			{"name": "votes", "value_type": "integer"},
			{"name": "accuracy", "value_type": "number"},
			{"name": "rank", "value_type": "number"},
			{"name": "grade", "value_type": "string"}
		]
	}`, table.ColumnsJSON(t))
	// Compare bytes, since JSONEq would decode the large integer as float64.
	assert.Equal(t,
		`[`+
			`{"input":{`+
			`"flag":true,`+
			`"count":9007199254740993,`+
			`"temperature":0.25,`+
			`"prompt":"draw <a> cat & dog",`+
			`"config":{"seed":7,"tags":["a","b"]},`+
			`"note":null`+
			`},`+
			`"output":{"answer":"a cat"},`+
			`"scores":{"passed":false,"votes":3,"accuracy":0.5,"rank":2,"grade":"B"}},`+
			`{"input":null,"output":null,`+
			`"scores":{"passed":null,"votes":null,"accuracy":null,"rank":null,"grade":null},`+
			`"example_key":"2"}`+
			`]`,
		table.RowsJSON(t))
}

func TestEncode_StringsAndNumbersLikeEncodingJSON(t *testing.T) {
	strs := []string{
		"",
		"plain",
		`quote " and backslash \`,
		"\b\f\n\r\t\x00\x1f\x7f",
		"<html> & </html>",
		"line and paragraph separators",
		"café ☕ 𝄞",
		"invalid \xff UTF-8",
	}
	numbers := []float64{
		0, math.Copysign(0, -1), 1, -1.5, 0.1, 1e-6, 1e-7, 123456789.125,
		1e20, 1e21, math.MaxFloat64, math.SmallestNonzeroFloat64,
	}

	var fields []*spb.EvalTableField
	var row []*spb.EvalTableValue
	var want []string
	for i, s := range strs {
		name := fmt.Sprintf("s%d", i)
		fields = append(fields,
			&spb.EvalTableField{Source: "input", Name: name, ValueType: "string"})
		row = append(row, stringValue(s))
		want = append(want, encodeJSON(t, name)+":"+encodeJSON(t, s))
	}
	for i, n := range numbers {
		name := fmt.Sprintf("n%d", i)
		fields = append(fields,
			&spb.EvalTableField{Source: "input", Name: name, ValueType: "number"})
		row = append(row, numberValue(n))
		want = append(want, encodeJSON(t, name)+":"+encodeJSON(t, n))
	}

	table, err := encode(t, &spb.UploadEvalTableRequest{
		DatasetFields: fields,
		Rows:          []*spb.EvalTableRow{{Input: values(row...)}},
	})

	require.NoError(t, err)
	assert.Equal(t,
		`[{"input":{`+strings.Join(want, ",")+`},"output":null,"scores":{}}]`,
		table.RowsJSON(t))
}

// encodeJSON encodes v like encoding/json without HTML escaping.
func encodeJSON(t *testing.T, v any) string {
	t.Helper()
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	require.NoError(t, encoder.Encode(v))
	return strings.TrimSuffix(buf.String(), "\n")
}

func TestUpload_DistinctIdempotencyKeys(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)
	request := &spb.UploadEvalTableRequest{
		Name: "my-table",
		Rows: []*spb.EvalTableRow{{}},
	}

	_, err := upload(context.Background(), uploader, request)
	require.NoError(t, err)
	_, err = upload(context.Background(), uploader, request)
	require.NoError(t, err)

	requests := ces.Requests()
	require.Len(t, requests, 8)
	keys := make(map[string]bool)
	for _, req := range requests {
		require.NotEmpty(t, req.IdempotencyKey, req.Path)
		keys[req.IdempotencyKey] = true
	}
	// Each request needs its own key, since CES rejects a reused key with a
	// different body. Uploading the same table again, such as from another
	// writer in shared mode, must not reuse the first upload's keys.
	assert.Len(t, keys, len(requests))
}

func TestUpload_RetriesReuseIdempotencyKey(t *testing.T) {
	evaltables.SetRetryWaitMinForTest(t, time.Millisecond)
	ces := newFakeCES(t)
	var failed atomic.Bool
	ces.errorStatus = func(path string) int {
		// Fail only the first rows request, with a status that makes the CES HTTP
		// client retry.
		if strings.HasSuffix(path, "/rows") && failed.CompareAndSwap(false, true) {
			return http.StatusServiceUnavailable
		}
		return 0
	}
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)

	_, err := upload(context.Background(), uploader, &spb.UploadEvalTableRequest{
		Name: "my-table",
		Rows: []*spb.EvalTableRow{{}},
	})
	require.NoError(t, err)

	var rowsRequests []cesRequest
	for _, req := range ces.Requests() {
		if strings.HasSuffix(req.Path, "/rows") {
			rowsRequests = append(rowsRequests, req)
		}
	}
	// The failed attempt and its retry. The retry must reuse the key so
	// that CES replays it instead of adding the rows again.
	require.Len(t, rowsRequests, 2)
	assert.Equal(t,
		rowsRequests[0].IdempotencyKey,
		rowsRequests[1].IdempotencyKey)
}

func TestUpload_StopsRetryingWhenCancelled(t *testing.T) {
	ces := newFakeCES(t)
	ctx, cancel := context.WithCancel(context.Background())
	// Cancel during a rows request that fails with a retryable status.
	ces.onRequest = func(path string) {
		if strings.HasSuffix(path, "/rows") {
			cancel()
		}
	}
	ces.errorStatus = func(path string) int {
		if strings.HasSuffix(path, "/rows") {
			return http.StatusServiceUnavailable
		}
		return 0
	}
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)

	_, err := upload(ctx, uploader, &spb.UploadEvalTableRequest{
		Name: "my-table",
		Rows: []*spb.EvalTableRow{{}},
	})

	assert.ErrorContains(t, err, "context canceled")
	// Create, columns, and one rows attempt.
	assert.Len(t, ces.Requests(), 3)
}

func TestUpload_SplitsRowsIntoBatches(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)

	// Each row is 1 MiB, so at most 7 fit under the 8 MiB target with the
	// surrounding JSON.
	_, err := upload(context.Background(), uploader, &spb.UploadEvalTableRequest{
		Name:          "t",
		DatasetFields: outputFieldX,
		Rows:          outputRows(10, 1<<20),
	})
	require.NoError(t, err)

	var batchSizes []int
	for _, req := range ces.Requests() {
		if !strings.HasSuffix(req.Path, "/rows") {
			continue
		}
		var body struct{ Rows []json.RawMessage }
		require.NoError(t, json.Unmarshal([]byte(req.Body), &body))
		assert.LessOrEqual(t, len(req.Body), 8<<20)
		batchSizes = append(batchSizes, len(body.Rows))
	}
	assert.Equal(t, []int{7, 3}, batchSizes)
}

func TestUpload_KeepsExampleKeysOfRowsWithoutInputs(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)

	// Each row is 3 MiB, so only two fit under the 8 MiB target.
	_, err := upload(context.Background(), uploader, &spb.UploadEvalTableRequest{
		Name:          "t",
		DatasetFields: outputFieldX,
		Rows:          outputRows(3, 3<<20),
	})
	require.NoError(t, err)

	type row struct {
		Input      json.RawMessage
		ExampleKey string `json:"example_key"`
	}
	var exampleKeys [][]string
	for _, req := range ces.Requests() {
		if !strings.HasSuffix(req.Path, "/rows") {
			continue
		}
		var body struct{ Rows []row }
		require.NoError(t, json.Unmarshal([]byte(req.Body), &body))
		var keys []string
		for _, r := range body.Rows {
			assert.Equal(t, "null", string(r.Input))
			keys = append(keys, r.ExampleKey)
		}
		exampleKeys = append(exampleKeys, keys)
	}
	assert.Equal(t, [][]string{{"1", "2"}, {"3"}}, exampleKeys)
}

func TestUpload_ReportsRowProgress(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)
	op := wboperation.NewOperations().New("uploading eval table t")
	var progress []string
	ces.onRequest = func(path string) {
		if strings.HasSuffix(path, "/rows") || strings.HasSuffix(path, "/versions") {
			progress = append(progress, op.ToProto().GetProgress())
		}
	}

	// Each row is 1 MiB, so the rows are sent in batches of 7 and 3.
	_, err := upload(op.Context(context.Background()), uploader,
		&spb.UploadEvalTableRequest{
			Name:          "t",
			DatasetFields: outputFieldX,
			Rows:          outputRows(10, 1<<20),
		})

	require.NoError(t, err)
	assert.Equal(t, []string{"", "7/10 rows", "10/10 rows"}, progress)
}

// writeRowsFile writes rows to a gzipped file, each preceded by its size as
// a varint.
func writeRowsFile(t *testing.T, rows ...*spb.EvalTableRow) string {
	t.Helper()
	var data []byte
	for _, row := range rows {
		message, err := proto.Marshal(row)
		require.NoError(t, err)
		data = binary.AppendUvarint(data, uint64(len(message)))
		data = append(data, message...)
	}
	return writeGzipFile(t, data)
}

func writeGzipFile(t *testing.T, data []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "rows.pb.gz")
	file, err := os.Create(path)
	require.NoError(t, err)
	gzWriter := gzip.NewWriter(file)
	_, err = gzWriter.Write(data)
	require.NoError(t, err)
	require.NoError(t, gzWriter.Close())
	require.NoError(t, file.Close())
	return path
}

func TestUpload_ReadsRowsFile(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)
	// Larger than bufio.Reader's buffer.
	long := strings.Repeat("a", 5_000)
	path := writeRowsFile(t,
		&spb.EvalTableRow{Output: values(stringValue("1"))},
		&spb.EvalTableRow{Output: values(stringValue(long))},
	)

	_, err := upload(context.Background(), uploader, &spb.UploadEvalTableRequest{
		Name:          "t",
		DatasetFields: outputFieldX,
		RowsFilePath:  path,
	})

	require.NoError(t, err)
	requests := ces.Requests()
	require.Len(t, requests, 4)
	assert.Equal(t,
		`{"rows":[`+
			`{"input":null,"output":{"x":"1"},"scores":{}},`+
			`{"input":null,"output":{"x":"`+long+`"},"scores":{}}`+
			`]}`,
		requests[2].Body)
}

func TestUpload_ReportsRowsFileProgress(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, projectFoundJSON)
	op := wboperation.NewOperations().New("uploading eval table t")

	_, err := upload(op.Context(context.Background()), uploader,
		&spb.UploadEvalTableRequest{
			Name:         "t",
			RowsFilePath: writeRowsFile(t, &spb.EvalTableRow{}, &spb.EvalTableRow{}),
		})

	require.NoError(t, err)
	assert.Equal(t, "2/2 rows", op.ToProto().GetProgress())
}

func TestEncode_RejectsInvalidRowInRowsFile(t *testing.T) {
	path := writeRowsFile(t,
		&spb.EvalTableRow{Output: values(stringValue("ok"))},
		&spb.EvalTableRow{Output: values(numberValue(1))},
	)

	_, err := encode(t, &spb.UploadEvalTableRequest{
		DatasetFields: outputFieldX,
		RowsFilePath:  path,
	})

	assert.ErrorContains(t, err, "(row 1)")
	assert.True(t, evaltables.IsUsageError(err))
}

func TestUpload_RejectsBadRowsFile(t *testing.T) {
	testCases := []struct {
		name    string
		write   func(t *testing.T) string
		wantErr string
	}{
		{
			name: "truncated row",
			// A row's size, but not the row.
			write:   func(t *testing.T) string { return writeGzipFile(t, binary.AppendUvarint(nil, 10)) },
			wantErr: "truncated row",
		},
		{
			name:    "oversized row",
			write:   func(t *testing.T) string { return writeGzipFile(t, binary.AppendUvarint(nil, 1<<30)) },
			wantErr: "row is 1073741824 bytes",
		},
		{
			name: "not gzip",
			write: func(t *testing.T) string {
				path := filepath.Join(t.TempDir(), "rows.pb.gz")
				require.NoError(t, os.WriteFile(path, []byte("not a gzip file"), 0o600))
				return path
			},
			wantErr: "gzip: invalid header",
		},
		{
			name: "gzip checksum mismatch",
			write: func(t *testing.T) string {
				path := writeRowsFile(t, &spb.EvalTableRow{})
				data, err := os.ReadFile(path)
				require.NoError(t, err)
				data[len(data)-8] ^= 0xff // The CRC-32 in the gzip trailer.
				require.NoError(t, os.WriteFile(path, data, 0o600))
				return path
			},
			wantErr: "gzip: invalid checksum",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			ces := newFakeCES(t)
			uploader, _ := newTestUploader(t, ces, projectFoundJSON)

			_, err := upload(context.Background(), uploader,
				&spb.UploadEvalTableRequest{Name: "t", RowsFilePath: tc.write(t)})

			assert.ErrorContains(t, err, "evaltables: failed to read rows: "+tc.wantErr)
			assert.Empty(t, ces.Requests())
		})
	}
}

func TestEncode_RejectsBothRowsAndRowsFile(t *testing.T) {
	_, err := encode(t, &spb.UploadEvalTableRequest{
		Rows:         []*spb.EvalTableRow{{}},
		RowsFilePath: writeRowsFile(t, &spb.EvalTableRow{}),
	})

	assert.ErrorContains(t, err, "both rows and a rows file")
	assert.True(t, evaltables.IsUsageError(err))
}

func TestUpload_NoCESURL(t *testing.T) {
	uploader, _ := newTestUploaderWithSettings(t, projectFoundJSON, settings.New())

	_, err := upload(context.Background(), uploader,
		&spb.UploadEvalTableRequest{Name: "t"})

	assert.ErrorContains(t, err, "no CES URL in settings")
	assert.False(t, evaltables.IsUsageError(err))
}

func TestUpload_ProjectNotFound(t *testing.T) {
	ces := newFakeCES(t)
	uploader, _ := newTestUploader(t, ces, `{"project": null}`)

	_, err := upload(context.Background(), uploader,
		&spb.UploadEvalTableRequest{Name: "t"})

	assert.ErrorContains(t, err, "project test-entity/test-project not found")
	assert.Empty(t, ces.Requests())
}

func TestEncode_RejectsUnknownColumnTypes(t *testing.T) {
	testCases := []struct {
		name    string
		request *spb.UploadEvalTableRequest
		wantErr string
	}{
		{
			name: "source",
			request: &spb.UploadEvalTableRequest{
				DatasetFields: []*spb.EvalTableField{
					{Source: "metadata", Name: "a", ValueType: "string"},
				},
			},
			wantErr: `field "a" has unknown source "metadata"`,
		},
		{
			name: "field value type",
			request: &spb.UploadEvalTableRequest{
				DatasetFields: []*spb.EvalTableField{
					{Source: "input", Name: "a", ValueType: "float"},
				},
			},
			wantErr: `field "a" has unknown value type "float"`,
		},
		{
			name: "scorer value type",
			request: &spb.UploadEvalTableRequest{
				Scorers: []*spb.EvalTableScorer{{Name: "a", ValueType: "json"}},
			},
			wantErr: `scorer "a" has unknown value type "json"`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, tc.request)

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}

func TestEncode_RejectsOversizedColumns(t *testing.T) {
	// Each "<" is escaped to 6 bytes, so the name alone exceeds the limit.
	name := strings.Repeat("<", 3<<20)
	_, err := encode(t, &spb.UploadEvalTableRequest{
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: name, ValueType: "string"},
		},
	})

	assert.ErrorContains(t, err, "columns request is")
}

func TestEncode_RejectsRowsThatDontFitColumns(t *testing.T) {
	testCases := []struct {
		name    string
		field   *spb.EvalTableField
		row     *spb.EvalTableRow
		wantErr string
	}{
		{
			name:    "too few input values",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Input: values()},
			wantErr: "row has 0 input values, expected 1 (row 0)",
		},
		{
			name:    "too many output values",
			field:   &spb.EvalTableField{Source: "output", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Output: values(nullValue(), nullValue())},
			wantErr: "row has 2 output values, expected 1 (row 0)",
		},
		{
			name:    "score without scorer",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Scores: []*spb.EvalTableValue{intValue(1)}},
			wantErr: "row has 1 score values, expected 0 (row 0)",
		},
		{
			name:    "string in integer column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "integer"},
			row:     &spb.EvalTableRow{Input: values(stringValue("1"))},
			wantErr: `field "a": string value in "integer" column`,
		},
		{
			name:    "number in integer column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "integer"},
			row:     &spb.EvalTableRow{Input: values(numberValue(1))},
			wantErr: `field "a": number value in "integer" column`,
		},
		{
			name:    "W&B media in JSON column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "json"},
			row:     &spb.EvalTableRow{Input: values(mediaValue(`{}`))},
			wantErr: `field "a": W&B media value in "json" column`,
		},
		{
			name: "JSON in media column",
			field: &spb.EvalTableField{
				Source:         "input",
				Name:           "a",
				ValueType:      "json",
				WandbMediaType: "image-file",
			},
			row:     &spb.EvalTableRow{Input: values(jsonValue(`{}`))},
			wantErr: `field "a": JSON value in image-file column`,
		},
		{
			name:    "invalid JSON",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "json"},
			row:     &spb.EvalTableRow{Input: values(jsonValue(`{"a":`))},
			wantErr: `field "a": invalid JSON`,
		},
		{
			name:    "NaN",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "number"},
			row:     &spb.EvalTableRow{Input: values(numberValue(math.NaN()))},
			wantErr: `field "a": unsupported number NaN`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, &spb.UploadEvalTableRequest{
				DatasetFields: []*spb.EvalTableField{tc.field},
				Rows:          []*spb.EvalTableRow{tc.row},
			})

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}

func TestEncode_RejectsOversizedRow(t *testing.T) {
	// Each "\n" is escaped to 2 bytes, so the encoded row exceeds 16 MiB.
	_, err := encode(t, &spb.UploadEvalTableRequest{
		DatasetFields: outputFieldX,
		Rows: []*spb.EvalTableRow{
			{Output: values(stringValue(strings.Repeat("\n", 8<<20)))},
		},
	})

	assert.ErrorContains(t, err, "row is")
	assert.ErrorContains(t, err, "(row 0)")
	assert.True(t, evaltables.IsUsageError(err))
}

func TestEncode_ConvertsMedia(t *testing.T) {
	// W&B media JSON, as from Python's Media.to_json.
	image := `{` +
		`"_type":"image-file",` +
		`"path":"media/eval_tables/images/eval/cat.png",` +
		`"sha256":"aaa",` +
		`"size":1024,` +
		`"format":"png",` +
		`"width":32,` +
		`"height":24,` +
		`"caption":"a cat",` +
		`"grouping":1,` +
		`"boxes":{"predictions":{` +
		`"_type":"boxes2D",` +
		`"path":"media/eval_tables/boxes/eval/cat.boxes2D.json",` +
		`"sha256":"bbb",` +
		`"size":10` +
		`}},` +
		`"masks":{"truth":{` +
		`"_type":"mask",` +
		`"artifact_path":"wandb-artifact://_id/abc/mask.png",` +
		`"sha256":"ccc",` +
		`"size":20` +
		`}}` +
		`}`
	audio := `{` +
		`"_type":"audio-file",` +
		`"artifact_path":"wandb-artifact://_id/def/meow.wav",` +
		`"_latest_artifact_path":"wandb-artifact://entity/project/sounds:latest/meow.wav",` +
		`"sha256":"ddd",` +
		`"size":2048,` +
		`"caption":"meow"` +
		`}`
	video := `{` +
		`"_type":"video-file",` +
		`"path":"media/eval tables/videos/cat#1.mp4",` +
		`"sha256":"eee",` +
		`"size":4096,` +
		`"width":64,` +
		`"height":48` +
		`}`

	table, err := encode(t, &spb.UploadEvalTableRequest{
		Name: "my-table",
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "prompt", ValueType: "string"},
			{Source: "output", Name: "answer", ValueType: "string"},
			{Source: "output", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
			{Source: "output", Name: "audio", ValueType: "json", WandbMediaType: "audio-file"},
			{Source: "output", Name: "video", ValueType: "json", WandbMediaType: "video-file"},
		},
		Rows: []*spb.EvalTableRow{{
			Input: values(stringValue("draw a cat")),
			Output: values(
				stringValue("a cat"),
				mediaValue(image),
				mediaValue(audio),
				mediaValue(video),
			),
		}},
	})

	require.NoError(t, err)
	assert.JSONEq(t, `{
		"dataset_fields": [
			{"source": "input", "name": "prompt", "value_type": "string"},
			{"source": "output", "name": "answer", "value_type": "string"},
			{
				"source": "output",
				"name": "image",
				"value_type": "json",
				"extension_type": "wandb-image",
				"extension_schema_version": 1
			},
			{
				"source": "output",
				"name": "audio",
				"value_type": "json",
				"extension_type": "wandb-audio",
				"extension_schema_version": 1
			},
			{
				"source": "output",
				"name": "video",
				"value_type": "json",
				"extension_type": "wandb-video",
				"extension_schema_version": 1
			}
		],
		"scorers": []
	}`, table.ColumnsJSON(t))
	assert.JSONEq(t, `[{
		"input": {"prompt": "draw a cat"},
		"output": {
			"answer": "a cat",
			"image": {
				"extension_type": "wandb-image",
				"schema_version": 1,
				"wb_media_type": "image-file",
				"format": "png",
				"sha256": "aaa",
				"size": 1024,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/images/eval/cat.png",
				"width": 32,
				"height": 24,
				"caption": "a cat",
				"boxes": {"predictions": {
					"_type": "boxes2D",
					"sha256": "bbb",
					"size": 10,
					"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/boxes/eval/cat.boxes2D.json"
				}},
				"masks": {"truth": {
					"_type": "mask",
					"sha256": "ccc",
					"size": 20,
					"uri": "wandb-artifact://_id/abc/mask.png"
				}}
			},
			"audio": {
				"extension_type": "wandb-audio",
				"schema_version": 1,
				"wb_media_type": "audio-file",
				"sha256": "ddd",
				"size": 2048,
				"uri": "wandb-artifact://_id/def/meow.wav",
				"caption": "meow"
			},
			"video": {
				"extension_type": "wandb-video",
				"schema_version": 1,
				"wb_media_type": "video-file",
				"sha256": "eee",
				"size": 4096,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval%20tables/videos/cat%231.mp4",
				"width": 64,
				"height": 48
			}
		},
		"scores": {}
	}]`, table.RowsJSON(t))
}

// TestEncode_ConvertsPythonMedia converts a request recorded from the Python
// SDK, so that it covers the W&B media JSON that Python actually sends.
//
// Python's test_eval_table_media_request_matches_core_fixture checks that the
// fixture is up to date.
func TestEncode_ConvertsPythonMedia(t *testing.T) {
	fixture, err := os.ReadFile("testdata/upload_media_request.json")
	require.NoError(t, err)
	request := &spb.UploadEvalTableRequest{}
	require.NoError(t, protojson.Unmarshal(fixture, request))
	request.Name = "my-table"

	table, err := encode(t, request)

	require.NoError(t, err)
	assert.JSONEq(t, `[{
		"input": {
			"image": {
				"extension_type": "wandb-image",
				"schema_version": 1,
				"wb_media_type": "image-file",
				"format": "png",
				"sha256": "3ac156facd9194daa57d0520cf7fae827b390b32e2a88aa63a6d2562e3d5321f",
				"size": 75,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/images/eval/3ac156facd9194daa57d0520cf7fae.png",
				"width": 2,
				"height": 2,
				"caption": "a cat",
				"boxes": {"predictions": {
					"_type": "boxes2D",
					"sha256": "ad1d2145f99572ff3c3a4fea99839c7ad570ad5359231e6e060d75caa250405f",
					"size": 113,
					"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/metadata/boxes2D/eval/ad1d2145f99572ff3c3a4fea99839c.boxes2D.json"
				}},
				"masks": {"predictions": {
					"_type": "mask",
					"sha256": "dd7b89993bde2e6c52ea00d533d1f09ac602d218251b7405d291fddc0b60cddf",
					"size": 68,
					"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/images/mask/eval/dd7b89993bde2e6c52ea00d533d1f0.mask.png"
				}}
			},
			"artifact_image": {
				"extension_type": "wandb-image",
				"schema_version": 1,
				"wb_media_type": "image-file",
				"format": "png",
				"sha256": "2f1686c393cd8b93b2b3d9ca90a271a87672a28dccb22d5688cd56561d34bdc5",
				"size": 75,
				"uri": "wandb-artifact://abc123/media/images/artifact.png",
				"width": 2,
				"height": 2
			},
			"audio": {
				"extension_type": "wandb-audio",
				"schema_version": 1,
				"wb_media_type": "audio-file",
				"sha256": "6583eae4b42ae05c5bea5d55837c8613de7898fc6ce0712ed26b961d6392f306",
				"size": 14,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/audio/eval/6583eae4b42ae05c5bea5d55837c86.wav",
				"caption": "meow"
			},
			"video": {
				"extension_type": "wandb-video",
				"schema_version": 1,
				"wb_media_type": "video-file",
				"sha256": "eb09cef0044f4d991fd75715493d7cb01fde6dcb5896fa3e6fc09ce25a4e841a",
				"size": 14,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/videos/eval/eb09cef0044f4d991fd75715493d7c.mp4",
				"width": 640,
				"height": 480,
				"caption": "a clip"
			}
		},
		"output": null,
		"scores": {}
	}]`, table.RowsJSON(t))
}

func TestEncode_KeepsNullMedia(t *testing.T) {
	table, err := encode(t, &spb.UploadEvalTableRequest{
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
			{Source: "output", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
		},
		Rows: []*spb.EvalTableRow{
			{Input: values(nullValue())},
			{Output: values(nullValue())},
		},
	})

	require.NoError(t, err)
	assert.Equal(t,
		`[`+
			`{"input":{"image":null},"output":null,"scores":{}},`+
			`{"input":null,"output":{"image":null},"scores":{}}`+
			`]`,
		table.RowsJSON(t))
}

func TestEncode_RejectsInvalidMedia(t *testing.T) {
	testCases := []struct {
		name      string
		mediaType string
		media     string
		wantErr   string
	}{
		{
			name:      "unknown media type",
			mediaType: "html-file",
			media:     `{"_type":"html-file","path":"a.html","sha256":"a","size":1}`,
			wantErr:   `field "media" has unknown media type "html-file"`,
		},
		{
			name:      "mismatched media type",
			mediaType: "image-file",
			media:     `{"_type":"audio-file","path":"a.wav","sha256":"a","size":1}`,
			wantErr:   `field "media": expected image-file media, got "audio-file"`,
		},
		{
			name:      "no file",
			mediaType: "audio-file",
			media:     `{"_type":"audio-file","sha256":"a","size":1}`,
			wantErr:   `field "media": media has no path or artifact path`,
		},
		{
			name:      "overlay without file",
			mediaType: "image-file",
			media: `{"_type":"image-file","path":"a.png","format":"png",` +
				`"sha256":"a","size":1,"boxes":{"b":{"_type":"boxes2D"}}}`,
			wantErr: `field "media": boxes "b": media has no path or artifact path`,
		},
		{
			name:      "invalid JSON",
			mediaType: "image-file",
			media:     `{"_type":`,
			wantErr:   `field "media": invalid media`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, &spb.UploadEvalTableRequest{
				DatasetFields: []*spb.EvalTableField{{
					Source:         "output",
					Name:           "media",
					ValueType:      "json",
					WandbMediaType: tc.mediaType,
				}},
				Rows: []*spb.EvalTableRow{{Output: values(mediaValue(tc.media))}},
			})

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}
