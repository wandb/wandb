package wbapi_test

import (
	"context"
	"encoding/base64"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestEvalTableHandlerWritesThroughGeneratedClient(t *testing.T) {
	type recordedRequest struct {
		path           string
		body           string
		idempotencyKey string
	}
	var requests []recordedRequest

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if !assert.NoError(t, err) {
			return
		}
		requests = append(requests, recordedRequest{
			path:           r.URL.Path,
			body:           string(body),
			idempotencyKey: r.Header.Get("Idempotency-Key"),
		})
		assert.Equal(
			t,
			"Basic "+base64.StdEncoding.EncodeToString([]byte("api:secret")),
			r.Header.Get("Authorization"),
		)
		w.Header().Set("Content-Type", "application/json")

		switch {
		case strings.HasSuffix(r.URL.Path, "/eval-tables"):
			_, _ = io.WriteString(w, `{"evaluation_id":"evaluation-1","dataset_id":"dataset-1"}`)
		case strings.HasSuffix(r.URL.Path, "/columns"):
			_, _ = io.WriteString(w, `{"dataset_fields":[],"scorers":[]}`)
		case strings.HasSuffix(r.URL.Path, "/rows"):
			_, _ = io.WriteString(w, `{"case_ids":[],"score_ids":[]}`)
		case strings.HasSuffix(r.URL.Path, "/versions"):
			_, _ = io.WriteString(w, `{"evaluation_version_id":"evaluation-version-1","dataset_version_id":"dataset-version-1"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	handler := wbapi.NewEvalTableHandler(
		api.NewAPIKeyCredentialProvider("secret"),
		settings.New(),
	)

	create := handler.HandleRequest(context.Background(), &spb.EvalTableRequest{
		BaseUrl:        server.URL,
		ScopeRef:       "scope-ref",
		IdempotencyKey: "create-key",
		Operation: &spb.EvalTableRequest_Create{
			Create: &spb.EvalTableCreateRequest{Name: "evaluation"},
		},
	})
	require.Nil(t, create.GetApiErrorResponse())
	assert.Equal(t, "evaluation-1", create.GetEvalTableResponse().GetEvaluationId())
	assert.Equal(t, "dataset-1", create.GetEvalTableResponse().GetDatasetId())

	columns := handler.HandleRequest(context.Background(), &spb.EvalTableRequest{
		BaseUrl:        server.URL,
		ScopeRef:       "scope-ref",
		IdempotencyKey: "columns-key",
		Operation: &spb.EvalTableRequest_CreateColumns{
			CreateColumns: &spb.EvalTableCreateColumnsRequest{
				EvaluationId: "evaluation-1",
				BodyJson: []byte(
					`{"dataset_fields":[{"name":"value","source":"input","value_type":"integer"}],"scorers":[]}`,
				),
			},
		},
	})
	require.Nil(t, columns.GetApiErrorResponse())

	rows := handler.HandleRequest(context.Background(), &spb.EvalTableRequest{
		BaseUrl:        server.URL,
		ScopeRef:       "scope-ref",
		IdempotencyKey: "rows-key",
		Operation: &spb.EvalTableRequest_AddRows{
			AddRows: &spb.EvalTableAddRowsRequest{
				EvaluationId: "evaluation-1",
				BodyJson: []byte(
					`{"rows":[{"input":{"value":9007199254740993},"output":null,"scores":{}}]}`,
				),
			},
		},
	})
	require.Nil(t, rows.GetApiErrorResponse())

	version := handler.HandleRequest(context.Background(), &spb.EvalTableRequest{
		BaseUrl:        server.URL,
		ScopeRef:       "scope-ref",
		IdempotencyKey: "version-key",
		Operation: &spb.EvalTableRequest_CreateVersion{
			CreateVersion: &spb.EvalTableCreateVersionRequest{
				EvaluationId: "evaluation-1",
			},
		},
	})
	require.Nil(t, version.GetApiErrorResponse())
	assert.Equal(
		t,
		"evaluation-version-1",
		version.GetEvalTableResponse().GetEvaluationVersionId(),
	)
	assert.Equal(
		t,
		"dataset-version-1",
		version.GetEvalTableResponse().GetDatasetVersionId(),
	)

	require.Len(t, requests, 4)
	assert.Equal(t, []string{
		"/v1/namespaces/wandb/scopes/scope-ref/eval-tables",
		"/v1/namespaces/wandb/scopes/scope-ref/eval-tables/evaluation-1/columns",
		"/v1/namespaces/wandb/scopes/scope-ref/eval-tables/evaluation-1/rows",
		"/v1/namespaces/wandb/scopes/scope-ref/eval-tables/evaluation-1/versions",
	}, []string{requests[0].path, requests[1].path, requests[2].path, requests[3].path})
	assert.Equal(t, []string{"create-key", "columns-key", "rows-key", "version-key"}, []string{
		requests[0].idempotencyKey,
		requests[1].idempotencyKey,
		requests[2].idempotencyKey,
		requests[3].idempotencyKey,
	})
	assert.Contains(t, requests[2].body, "9007199254740993")
}

func TestEvalTableHandlerRejectsMalformedRowsBeforeNetwork(t *testing.T) {
	handler := wbapi.NewEvalTableHandler(
		api.NoopCredentialProvider{},
		settings.New(),
	)

	response := handler.HandleRequest(context.Background(), &spb.EvalTableRequest{
		BaseUrl:        "https://evaluations.example.test",
		ScopeRef:       "scope-ref",
		IdempotencyKey: "rows-key",
		Operation: &spb.EvalTableRequest_AddRows{
			AddRows: &spb.EvalTableAddRowsRequest{
				EvaluationId: "evaluation-1",
				BodyJson:     []byte(`{"rows":`),
			},
		},
	})

	require.NotNil(t, response.GetApiErrorResponse())
	assert.Contains(t, response.GetApiErrorResponse().GetMessage(), "decode EvalTable rows")
}
