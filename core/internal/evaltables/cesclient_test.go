package evaltables_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	ces "github.com/wandb/cwevals-go"
	"github.com/wandb/cwevals-go/option"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/evaltables"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var newTableParams = ces.EvalTableNewParams{
	ScopeID: ces.F("scope"),
	Name:    ces.F("table"),
}

func newTestService(t *testing.T, cesURL string) *ces.EvalTableService {
	t.Helper()
	service, err := evaltables.NewEvalTableService(
		api.NewAPIKeyCredentialProvider("run-api-key"),
		observabilitytest.NewTestLogger(t).Logger,
		settings.From(&spb.Settings{XCesBaseUrl: wrapperspb.String(cesURL)}),
	)
	require.NoError(t, err)
	return service
}

func TestEvalTableService_UsesGivenURLAndRunCredentials(t *testing.T) {
	server := apitest.NewRecordingServer()
	defer server.Close()
	t.Setenv("CES_BASE_URL", "https://ces.example.com")
	t.Setenv("WANDB_API_KEY", "env-api-key")
	t.Setenv("WANDB_ACCESS_TOKEN", "env-access-token")
	t.Setenv("CES_CUSTOM_HEADERS", "X-From-Env: yes")
	service := newTestService(t, server.URL+"/evaluations")

	// The recording server's empty response fails to decode; only the
	// request matters here.
	_, _ = service.New(context.Background(), newTableParams)

	requests := server.Requests()
	require.Len(t, requests, 1)
	req := requests[0]
	assert.Equal(t,
		"/evaluations/v1/namespaces/wandb/scopes/scope/eval-tables",
		req.URL.Path)
	assert.Equal(t,
		"Basic YXBpOnJ1bi1hcGkta2V5", // "api:run-api-key"
		req.Header.Get("Authorization"))
	assert.Equal(t, "yes", req.Header.Get("X-From-Env"))
}

func TestEvalTableService_SendsCredentialsOnlyToCESURL(t *testing.T) {
	cesServer := apitest.NewRecordingServer()
	defer cesServer.Close()
	otherServer := apitest.NewRecordingServer()
	defer otherServer.Close()
	t.Setenv("WANDB_API_KEY", "env-api-key")
	service := newTestService(t, cesServer.URL+"/evaluations")

	for _, baseURL := range []string{
		cesServer.URL + "/evaluations",
		cesServer.URL + "/other",
		otherServer.URL + "/evaluations",
	} {
		_, _ = service.New(context.Background(), newTableParams,
			option.WithBaseURL(baseURL))
	}

	cesRequests := cesServer.Requests()
	require.Len(t, cesRequests, 2)
	assert.NotEmpty(t, cesRequests[0].Header.Get("Authorization"))
	assert.Empty(t, cesRequests[1].Header.Get("Authorization"))
	otherRequests := otherServer.Requests()
	require.Len(t, otherRequests, 1)
	assert.Empty(t, otherRequests[0].Header.Get("Authorization"))
}

func TestNewEvalTableService_NoURL(t *testing.T) {
	_, err := evaltables.NewEvalTableService(
		api.NewAPIKeyCredentialProvider("run-api-key"),
		observabilitytest.NewTestLogger(t).Logger,
		settings.New(),
	)

	assert.ErrorContains(t, err, "no CES URL")
}

func TestNewEvalTableService_InvalidURL(t *testing.T) {
	_, err := evaltables.NewEvalTableService(
		api.NewAPIKeyCredentialProvider("run-api-key"),
		observabilitytest.NewTestLogger(t).Logger,
		settings.From(&spb.Settings{XCesBaseUrl: wrapperspb.String("://bad")}),
	)

	assert.ErrorContains(t, err, "invalid CES URL")
}
