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

func TestDatasetNewWithOptionalParams(t *testing.T) {
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
	_, err := client.Datasets.New(context.TODO(), cwevals.DatasetNewParams{
		Namespace: cwevals.F("wandb"),
		ScopeID:   cwevals.F("scope_id"),
		Name:      cwevals.F("x"),
		Attributes: cwevals.F(map[string]interface{}{
			"foo": "bar",
		}),
		Uri: cwevals.F("https://example.com"),
	})
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestDatasetUpdateWithOptionalParams(t *testing.T) {
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
	_, err := client.Datasets.Update(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetUpdateParams{
			Namespace: cwevals.F("wandb"),
			ScopeID:   cwevals.F("scope_id"),
			Attributes: cwevals.F(map[string]interface{}{
				"foo": "bar",
			}),
			Name: cwevals.F("x"),
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

func TestDatasetListWithOptionalParams(t *testing.T) {
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
	_, err := client.Datasets.List(context.TODO(), cwevals.DatasetListParams{
		Namespace: cwevals.F("wandb"),
		ScopeID:   cwevals.F("scope_id"),
		Cursor:    cwevals.F("cursor"),
		Limit:     cwevals.F(int64(1)),
		Name:      cwevals.F("x"),
	})
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestDatasetDelete(t *testing.T) {
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
	err := client.Datasets.Delete(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetDeleteParams{
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

func TestDatasetGet(t *testing.T) {
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
	_, err := client.Datasets.Get(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetGetParams{
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
