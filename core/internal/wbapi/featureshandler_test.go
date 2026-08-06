package wbapi_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/wbapi"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestFeaturesHandlerReturnsRequestedOrganizationFeatures(t *testing.T) {
	tests := []struct {
		name    string
		respMap map[string]any
		want    map[string]bool
	}{
		{
			name: "filters results and preserves disabled values",
			respMap: map[string]any{
				"organization": map[string]any{
					"featureFlags": []any{
						map[string]any{"rampKey": "enabled-feat", "isEnabled": true},
						map[string]any{"rampKey": "disabled-feat", "isEnabled": false},
						map[string]any{"rampKey": "unrequested-feat", "isEnabled": true},
						nil,
					},
				},
			},
			want: map[string]bool{
				"enabled-feat":  true,
				"disabled-feat": false,
			},
		},
		{
			name:    "missing organization",
			respMap: map[string]any{"organization": nil},
			want:    map[string]bool{},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			client := &fakeGQLClient{respMap: test.respMap}
			handler := newTestFeaturesHandler(client)

			response := handler.HandleOrgRequest(
				context.Background(),
				&spb.OrgFeaturesRequest{
					Org: "test-org",
					Features: []string{
						"enabled-feat",
						"disabled-feat",
						"missing-feat",
					},
				},
			)

			featuresResponse := response.GetOrgFeaturesResponse()
			require.NotNil(t, featuresResponse)
			assert.Equal(t, test.want, featuresResponse.GetFeatures())
			require.True(t, client.called)
			assert.Equal(t, "OrgFeatureFlags", client.gotReq.OpName)

			variablesJSON, err := json.Marshal(client.gotReq.Variables)
			require.NoError(t, err)
			var variables map[string]any
			require.NoError(t, json.Unmarshal(variablesJSON, &variables))
			assert.Equal(t, "test-org", variables["org"])
		})
	}
}

func TestFeaturesHandlerRequiresOrgForOrgFeatures(t *testing.T) {
	client := &fakeGQLClient{}
	handler := newTestFeaturesHandler(client)

	response := handler.HandleOrgRequest(
		context.Background(),
		&spb.OrgFeaturesRequest{Features: []string{"feature"}},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), "org is required")
	assert.False(t, client.called)
}

func TestFeaturesHandlerWithNoOrgFeaturesSkipsQuery(t *testing.T) {
	client := &fakeGQLClient{}
	handler := newTestFeaturesHandler(client)

	response := handler.HandleOrgRequest(
		context.Background(),
		&spb.OrgFeaturesRequest{Org: "test-org"},
	)

	require.NotNil(t, response.GetOrgFeaturesResponse())
	assert.Empty(t, response.GetOrgFeaturesResponse().GetFeatures())
	assert.False(t, client.called)
}

func TestFeaturesHandlerReturnsOrganizationFeatureQueryError(t *testing.T) {
	client := &fakeGQLClient{err: assert.AnError}
	handler := newTestFeaturesHandler(client)

	response := handler.HandleOrgRequest(
		context.Background(),
		&spb.OrgFeaturesRequest{
			Org:      "test-org",
			Features: []string{"feature"},
		},
	)

	apiError := response.GetApiErrorResponse()
	require.NotNil(t, apiError)
	assert.Contains(t, apiError.GetMessage(), assert.AnError.Error())
}

func TestFeaturesHandlerStillReturnsServerFeatures(t *testing.T) {
	client := &fakeGQLClient{}
	handler := wbapi.NewFeaturesHandler(
		client,
		featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
			spb.ServerFeature_CLIENT_IDS: true,
		}),
	)

	response := handler.HandleRequest(
		context.Background(),
		&spb.FeaturesRequest{
			Features: []spb.ServerFeature{
				spb.ServerFeature_CLIENT_IDS,
			},
		},
	)

	require.NotNil(t, response.GetFeaturesResponse())
	assert.Equal(
		t,
		[]spb.ServerFeature{spb.ServerFeature_CLIENT_IDS},
		response.GetFeaturesResponse().GetEnabled(),
	)
	assert.False(t, client.called)
}

func newTestFeaturesHandler(client *fakeGQLClient) *wbapi.FeaturesHandler {
	return wbapi.NewFeaturesHandler(
		client,
		featurechecker.NewPreloaded(nil),
	)
}
