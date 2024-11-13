package api

import (
	"context"
	"net/http"
	"strings"
)

//go:generate oapi-codegen -config openapi.client.yaml https://raw.githubusercontent.com/ctrlplanedev/ctrlplane/refs/heads/main/openapi.v1.json

func NewAPIKeyClientWithResponses(server string, apiKey string) (*ClientWithResponses, error) {
	server = strings.TrimSuffix(server, "/")
	server = strings.TrimSuffix(server, "/api")
	return NewClientWithResponses(server+"/api",
		WithRequestEditorFn(func(ctx context.Context, req *http.Request) error {
			req.Header.Set("X-API-Key", apiKey)
			return nil
		}),
	)
}
