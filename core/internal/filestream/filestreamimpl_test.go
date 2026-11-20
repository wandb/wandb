package filestream

import (
	"errors"
	"sync"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestStopState_FeedbackTable(t *testing.T) {
	tests := []struct {
		name     string
		feedback []any
		want     bool
	}{
		{"default false", nil, false},
		{"false only -> false", []any{false}, false},
		{"true only -> true", []any{true}, true},
		{"false, non-bool, true -> true", []any{false, true}, true},
		{"true, non-bool, false -> true", []any{true, false}, true},
		{"non-bool ignored", []any{"nope", 1}, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var fs fileStream
			ch := make(chan map[string]any, len(tc.feedback))
			var wg sync.WaitGroup
			fs.startProcessingFeedback(ch, &wg)

			for _, v := range tc.feedback {
				ch <- map[string]any{"stopped": v}
			}
			close(ch)
			wg.Wait()

			if got := fs.IsStopped(); got != tc.want {
				t.Fatalf("StopState = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestInitialState_SummaryDelta(t *testing.T) {
	const query = "ProjectAcceptsSummaryDelta"
	tests := []struct {
		name    string
		feature bool
		stub    func(*gqlmock.MockClient)
		want    bool
	}{
		{"accepted", true, func(c *gqlmock.MockClient) {
			c.StubMatchOnce(gqlmock.WithOpName(query),
				`{"project": {"acceptsSummaryDelta": true}}`)
		}, true},
		{"not accepted", true, func(c *gqlmock.MockClient) {
			c.StubMatchOnce(gqlmock.WithOpName(query),
				`{"project": {"acceptsSummaryDelta": false}}`)
		}, false},
		{"no project", true, func(c *gqlmock.MockClient) {
			c.StubMatchOnce(gqlmock.WithOpName(query), `{"project": null}`)
		}, false},
		{"query fails", true, func(c *gqlmock.MockClient) {
			c.StubMatchWithError(gqlmock.WithOpName(query), errors.New("down"))
		}, false},
		{"server without the feature is not asked", false, nil, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			client := gqlmock.NewMockClient()
			if tc.stub != nil {
				tc.stub(client)
			}
			fs := &fileStream{
				beforeRunEndCtx: t.Context(),
				settings:        settings.New(),
				logger:          observabilitytest.NewTestLogger(t),
				graphqlClient:   client,
				featureProvider: featurechecker.NewPreloaded(
					map[spb.ServerFeature]bool{
						spb.ServerFeature_FILESTREAM_SUMMARY_DELTA: tc.feature,
					}),
			}

			state := fs.initialState("entity", "project", nil)

			assert.Equal(t, tc.want, state.SummaryDelta)
			assert.True(t, client.AllStubsUsed())
			if !tc.feature {
				assert.Empty(t, client.AllRequests())
			}
		})
	}
}

func TestInitialState_SlowFeatureLookupFallsBackToFull(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		client := gqlmock.NewMockClient()
		client.StubMatchHang(gqlmock.WithOpName("ServerFeaturesQuery"))
		logger := observabilitytest.NewTestLogger(t)
		fs := &fileStream{
			beforeRunEndCtx: t.Context(),
			settings:        settings.New(),
			logger:          logger,
			graphqlClient:   client,
			featureProvider: featurechecker.New(client, logger),
		}

		start := time.Now()
		state := fs.initialState("entity", "project", nil)
		assert.False(t, state.SummaryDelta)
		assert.Equal(t, summaryDeltaQueryTimeout, time.Since(start))
		assert.Len(t, client.AllRequests(), 1)
	})
}

func TestInitialState_NoGraphqlClient(t *testing.T) {
	fs := &fileStream{
		beforeRunEndCtx: t.Context(),
		settings:        settings.New(),
		featureProvider: featurechecker.NewPreloaded(
			map[spb.ServerFeature]bool{
				spb.ServerFeature_FILESTREAM_SUMMARY_DELTA: true,
			}),
	}

	state := fs.initialState("entity", "project", FileStreamOffsetMap{
		HistoryChunk: 7,
	})

	assert.False(t, state.SummaryDelta)
	assert.Equal(t, 7, state.HistoryLineNum)
}
