package runhandle_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeTelemetryRecord returns a fake TelemetryRecord for testing.
func fakeTelemetryRecord() *spb.TelemetryRecord {
	return &spb.TelemetryRecord{
		Feature: &spb.Feature{Save: true},
	}
}

// fakeTelemetryEncoded returns the encoded version of fakeTelemetryRecord
// that would be uploaded in an UpsertBucket request.
func fakeTelemetryEncoded() *runupsertertest.Telemetry {
	return &runupsertertest.Telemetry{FeatureNumbers: []int{3}} // 3 = save
}

func TestUpdateTelemetry_BeforeInit(t *testing.T) {
	runHandle := runhandle.New()
	mockGQL := gqlmock.NewMockClient()
	runupsertertest.StubUpsertBucket(t, mockGQL)
	runupsertertest.StubUpsertBucket(t, mockGQL)
	upserter := runupsertertest.NewTestUpserter(t,
		"test-entity", "test-project", "test-run",
		runupserter.RunUpserterParams{
			GraphqlClientOrNil: mockGQL,
		})

	runHandle.UpdateTelemetry(fakeTelemetryRecord())
	require.NoError(t, runHandle.Init(upserter))
	upserter.Finish()

	telemetry := runupsertertest.UpsertBucketTelemetry(t, mockGQL.AllRequests())
	assert.Equal(t, fakeTelemetryEncoded(), telemetry)
}

func TestUpdateTelemetry_AfterInit(t *testing.T) {
	runHandle := runhandle.New()
	mockGQL := gqlmock.NewMockClient()
	runupsertertest.StubUpsertBucket(t, mockGQL)
	runupsertertest.StubUpsertBucket(t, mockGQL)
	upserter := runupsertertest.NewTestUpserter(t,
		"test-entity", "test-project", "test-run",
		runupserter.RunUpserterParams{
			GraphqlClientOrNil: mockGQL,
		})

	require.NoError(t, runHandle.Init(upserter))
	runHandle.UpdateTelemetry(fakeTelemetryRecord())
	upserter.Finish()

	telemetry := runupsertertest.UpsertBucketTelemetry(t, mockGQL.AllRequests())
	assert.Equal(t, fakeTelemetryEncoded(), telemetry)
}
