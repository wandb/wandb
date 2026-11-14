// File generated from our OpenAPI spec by Stainless.

package cwevals_test

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/wandb/cwevals-go"
	"github.com/wandb/cwevals-go/internal/testutil"
	"github.com/wandb/cwevals-go/option"
)

func TestDatasetTrajectoryNew(t *testing.T) {
	baseURL := "http://localhost:4010"
	if envURL, ok := os.LookupEnv("TEST_API_BASE_URL"); ok {
		baseURL = envURL
	}
	if !testutil.CheckTestServer(t, baseURL) {
		return
	}
	client := cwevals.NewClient(
		option.WithBaseURL(baseURL),
		option.WithBearerToken("My Bearer Token"),
		option.WithUsername("My Username"),
		option.WithAPIKey("My API Key"),
	)
	_, err := client.Datasets.Trajectories.New(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetTrajectoryNewParams{
			Namespace: cwevals.F("wandb"),
			ScopeID:   cwevals.F("scope_id"),
			Trajectories: cwevals.F([]cwevals.DatasetTrajectoryNewParamsTrajectory{{
				Name:               cwevals.F("x"),
				RootCaseID:         cwevals.F("182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e"),
				ParentTrajectoryID: cwevals.F("182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e"),
			}}),
		},
	)
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestDatasetTrajectoryListWithOptionalParams(t *testing.T) {
	baseURL := "http://localhost:4010"
	if envURL, ok := os.LookupEnv("TEST_API_BASE_URL"); ok {
		baseURL = envURL
	}
	if !testutil.CheckTestServer(t, baseURL) {
		return
	}
	client := cwevals.NewClient(
		option.WithBaseURL(baseURL),
		option.WithBearerToken("My Bearer Token"),
		option.WithUsername("My Username"),
		option.WithAPIKey("My API Key"),
	)
	_, err := client.Datasets.Trajectories.List(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetTrajectoryListParams{
			Namespace: cwevals.F("wandb"),
			ScopeID:   cwevals.F("scope_id"),
			Cursor:    cwevals.F("cursor"),
			Limit:     cwevals.F(int64(1)),
		},
	)
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestDatasetTrajectoryGet(t *testing.T) {
	baseURL := "http://localhost:4010"
	if envURL, ok := os.LookupEnv("TEST_API_BASE_URL"); ok {
		baseURL = envURL
	}
	if !testutil.CheckTestServer(t, baseURL) {
		return
	}
	client := cwevals.NewClient(
		option.WithBaseURL(baseURL),
		option.WithBearerToken("My Bearer Token"),
		option.WithUsername("My Username"),
		option.WithAPIKey("My API Key"),
	)
	_, err := client.Datasets.Trajectories.Get(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetTrajectoryGetParams{
			Namespace: cwevals.F("wandb"),
			ScopeID:   cwevals.F("scope_id"),
		},
	)
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}
