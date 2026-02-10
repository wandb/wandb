package runupsertertest

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// NewOfflineUpserter creates a RunUpserter that acts as if it's offline
// and makes no requests.
func NewOfflineUpserter(t *testing.T) *runupserter.RunUpserter {
	t.Helper()
	return NewTestUpserter(t,
		"test-entity", "test-project", "test-run",
		runupserter.RunUpserterParams{},
	)
}

// NewTestUpserter creates a RunUpserter with test defaults for required
// parameters that are unspecified.
func NewTestUpserter(
	t *testing.T,
	entity, project, runID string,
	params runupserter.RunUpserterParams,
) *runupserter.RunUpserter {
	t.Helper()

	if params.DebounceDelay == nil {
		params.DebounceDelay = waiting.NoDelay()
	}
	if params.ClientID == "" {
		params.ClientID = "test-client-id"
	}
	if params.Settings == nil {
		params.Settings = settings.New()
	}
	if params.BeforeRunEndCtx == nil {
		params.BeforeRunEndCtx = context.Background()
	}
	if params.Logger == nil {
		params.Logger = observabilitytest.NewTestLogger(t)
	}
	if params.FeatureProvider == nil {
		params.FeatureProvider = featurechecker.NewServerFeaturesCache(nil, params.Logger)
	}

	record := &spb.Record{RecordType: &spb.Record_Run{
		Run: &spb.RunRecord{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
		},
	}}

	upserter, err := runupserter.InitRun(record, params)
	require.NoError(t, err)

	return upserter
}

// StubUpsertBucket stubs a single call to UpsertBucket to return a basic
// response.
func StubUpsertBucket(t *testing.T, mockGQL *gqlmock.MockClient) {
	mockGQL.StubMatchOnce(gqlmock.WithOpName("UpsertBucket"), `{
		"upsertBucket": {
			"bucket": {
				"id": "storage ID",
				"name": "run ID",
				"displayName": "display name",
				"sweepName": "sweep ID",
				"project": {
					"name": "project name",
					"entity": {"name": "entity name"}
				}
			}
		}
	}`)
}

// Telemetry is the telemetry uploaded through an UpsertBucket request.
type Telemetry struct {
	// FeatureNumbers is the list of enabled features, specified by their
	// field numbers in the telemetry Feature proto.
	FeatureNumbers []int `json:"3"`
}

// upsertBucketConfig is the structure of an UpsertBucket config string.
type upsertBucketConfig struct {
	Internal struct {
		Value struct {
			Telemetry *Telemetry `json:"t"`
		}
	} `json:"_wandb"`
}

// UpsertBucketTelemetry extracts the final telemetry uploaded by the run
// upserter given a sequence of requests.
func UpsertBucketTelemetry(
	t *testing.T,
	requests []*graphql.Request,
) *Telemetry {
	t.Helper()

	for i := range len(requests) {
		// Loop in reverse and take the last value.
		idx := len(requests) - i - 1
		request := requests[idx]

		if request.OpName != "UpsertBucket" {
			continue
		}

		input := jsonMarshalToMap(t, request.Variables)
		config, hasConfig := input["config"]
		if !hasConfig {
			continue
		}

		configString := config.(string)
		var configValue upsertBucketConfig
		err := json.Unmarshal([]byte(configString), &configValue)
		require.NoError(t, err)

		return configValue.Internal.Value.Telemetry
	}

	return nil
}

// jsonMarshalToMap converts a value to a map by marshalling to JSON and
// unmarshalling.
func jsonMarshalToMap(t *testing.T, value any) (ret map[string]any) {
	bytes, err := json.Marshal(value)
	require.NoError(t, err)

	err = json.Unmarshal(bytes, &ret)
	require.NoError(t, err)

	return ret
}
