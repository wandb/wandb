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

func TestScorerNewWithOptionalParams(t *testing.T) {
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
	_, err := client.Scorers.New(context.TODO(), cwevals.ScorerNewParams{
		Namespace: cwevals.F("wandb"),
		ScopeID:   cwevals.F("scope_id"),
		AllowedTargetKinds: cwevals.F(
			[]cwevals.ScorerNewParamsAllowedTargetKind{cwevals.ScorerNewParamsAllowedTargetKindCase},
		),
		Name:        cwevals.F("x"),
		ValueType:   cwevals.F(cwevals.ScorerNewParamsValueTypeNull),
		Description: cwevals.F("description"),
	})
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestScorerListWithOptionalParams(t *testing.T) {
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
	_, err := client.Scorers.List(context.TODO(), cwevals.ScorerListParams{
		Namespace: cwevals.F("wandb"),
		ScopeID:   cwevals.F("scope_id"),
		Cursor:    cwevals.F("cursor"),
		Limit:     cwevals.F(int64(1)),
	})
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

func TestScorerDelete(t *testing.T) {
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
	err := client.Scorers.Delete(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.ScorerDeleteParams{
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

func TestScorerGet(t *testing.T) {
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
	_, err := client.Scorers.Get(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.ScorerGetParams{
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
