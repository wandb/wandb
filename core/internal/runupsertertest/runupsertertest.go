package runupsertertest

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// NewOfflineUpserter creates a RunUpserter that acts as if it's offline
// and makes no requests.
func NewOfflineUpserter(t *testing.T) *runupserter.RunUpserter {
	t.Helper()

	testLogger := observabilitytest.NewTestLogger(t)

	record := &spb.Record{RecordType: &spb.Record_Run{
		Run: &spb.RunRecord{
			Entity:  "test-entity",
			Project: "test-project",
			RunId:   "test-run",
		},
	}}
	params := runupserter.RunUpserterParams{
		DebounceDelay:      waiting.NoDelay(),
		ClientID:           "test-client-id",
		Settings:           settings.New(),
		BeforeRunEndCtx:    context.Background(),
		Operations:         wboperation.NewOperations(),
		FeatureProvider:    featurechecker.NewServerFeaturesCache(nil, testLogger),
		GraphqlClientOrNil: nil,
		Logger:             testLogger,
	}

	upserter, err := runupserter.InitRun(record, params)
	require.NoError(t, err)

	return upserter
}
