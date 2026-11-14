// File generated from our OpenAPI spec by Stainless.

package cwevals_test

import (
	"context"
	"os"
	"testing"

	"github.com/wandb/cwevals-go"
	"github.com/wandb/cwevals-go/internal/testutil"
	"github.com/wandb/cwevals-go/option"
)

func TestUsage(t *testing.T) {
	baseURL := "http://localhost:4010"
	if envURL, ok := os.LookupEnv("TEST_API_BASE_URL"); ok {
		baseURL = envURL
	}
	if !testutil.CheckTestServer(t, baseURL) {
		return
	}
	client := cwevals.NewClient(
		option.WithBaseURL(baseURL),
		option.WithUsername("My Username"),
		option.WithAPIKey("My API Key"),
	)
	service, err := client.Service.Get(context.TODO())
	if err != nil {
		t.Error(err)
		return
	}
	t.Logf("%+v\n", service.Message)
}
