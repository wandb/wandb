package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func viewerBackend(t *testing.T, response string) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(response))
		}))
	t.Cleanup(server.Close)
	return server
}

func TestHandleAuthenticateAcceptsPartialErrors(t *testing.T) {
	// Field-level GraphQL errors (here: a failing email resolver) must not
	// invalidate credentials when the viewer and its entity were resolved.
	backend := viewerBackend(t,
		`{
			"data": {"viewer": {"id": "id", "entity": "myentity"}},
			"errors": [{"message": "email resolver failed"}]
		}`)

	nc := &Connection{}
	response := nc.handleAuthenticateImpl(
		context.Background(),
		&spb.ServerAuthenticateRequest{
			ApiKey:  "X",
			BaseUrl: backend.URL,
		},
	)

	if response.GetErrorStatus() != "" {
		t.Fatalf("expected success, got error status %q", response.GetErrorStatus())
	}
	if response.GetDefaultEntity() != "myentity" {
		t.Fatalf("expected entity, got %q", response.GetDefaultEntity())
	}
}

func TestHandleAuthenticateNullViewerIsInvalid(t *testing.T) {
	backend := viewerBackend(t, `{"data": {"viewer": null}}`)

	nc := &Connection{}
	response := nc.handleAuthenticateImpl(
		context.Background(),
		&spb.ServerAuthenticateRequest{
			ApiKey:  "X",
			BaseUrl: backend.URL,
		},
	)

	if response.GetErrorStatus() == "" {
		t.Fatal("expected an error status for a null viewer")
	}
}
