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
	finishInit := runHandle.WillInit()
	defer finishInit()
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

	finishInit := runHandle.WillInit()
	defer finishInit()
	require.NoError(t, runHandle.Init(upserter))
	runHandle.UpdateTelemetry(fakeTelemetryRecord())
	upserter.Finish()

	telemetry := runupsertertest.UpsertBucketTelemetry(t, mockGQL.AllRequests())
	assert.Equal(t, fakeTelemetryEncoded(), telemetry)
}

func TestInit(t *testing.T) {
	runHandle := runhandle.New()
	finishInit := runHandle.WillInit()
	defer finishInit()
	expectedUpserter := runupsertertest.NewOfflineUpserter(t)

	require.NoError(t, runHandle.Init(expectedUpserter))
	upserter, err := runHandle.Upserter()

	assert.NoError(t, err)
	assert.Equal(t, expectedUpserter, upserter)
}

func TestInit_BeforeWillInit_Fails(t *testing.T) {
	runHandle := runhandle.New()
	expectedUpserter := runupsertertest.NewOfflineUpserter(t)

	err := runHandle.Init(expectedUpserter)

	assert.ErrorContains(t, err, "did not call WillInit")
}

func TestInit_Twice_Fails(t *testing.T) {
	runHandle := runhandle.New()
	finishInit := runHandle.WillInit()
	defer finishInit()
	upserter := runupsertertest.NewOfflineUpserter(t)

	require.NoError(t, runHandle.Init(upserter))
	err := runHandle.Init(upserter)

	assert.ErrorContains(t, err, "run already initialized")
}

func TestInit_Nil_Fails(t *testing.T) {
	runHandle := runhandle.New()

	assert.ErrorContains(t, runHandle.Init(nil), "nil upserter")
}

func TestWillInit(t *testing.T) {
	runHandle := runhandle.New()
	assert.False(t, runHandle.BeganInit())

	finishInit := runHandle.WillInit()
	finishInit()
	upserter, err := runHandle.Upserter()

	assert.True(t, runHandle.BeganInit())
	assert.Nil(t, upserter)
	assert.ErrorContains(t, err, "run failed to initialize")
}

func TestNotInitialized(t *testing.T) {
	runHandle := runhandle.New()

	upserter, err := runHandle.Upserter()

	assert.Nil(t, upserter)
	assert.ErrorContains(t, err, "run not yet initialized")
}
