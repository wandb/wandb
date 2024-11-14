package api

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
)

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

func (v *Variable_Value) SetString(value string) {
	v.union = json.RawMessage("\"" + value + "\"")
}
