package leet

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	"github.com/wandb/wandb/core/internal/observability"
)

func newComputeClients(baseURL string) (*remoteClients, error) {
	return newRemoteClientsWithRetryPolicy(baseURL, observability.NewNoOpLogger(),
		func(ctx context.Context, response *http.Response, err error) (bool, error) {
			// Return Connect error bodies intact, including server errors.
			if response != nil {
				return false, nil
			}
			return retryablehttp.DefaultRetryPolicy(ctx, response, err)
		})
}

// computeCall uses the remote layer's authenticated HTTP client for Connect JSON.
func (c *remoteClients) computeCall(baseURL, method string, request, response proto.Message) error {
	body, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(request)
	if err != nil {
		return err
	}
	ctx, cancel := remoteContext()
	defer cancel()
	req, err := retryablehttp.NewRequestWithContext(ctx, http.MethodPost,
		baseURL+"/compute.v1.ComputeService/"+method, body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Connect-Protocol-Version", "1")
	resp, err := c.http.Do(req)
	if err != nil {
		return &QueryError{Code: "not_available", Message: err.Error()}
	}
	defer resp.Body.Close()
	body, err = io.ReadAll(resp.Body)
	if err != nil {
		return &QueryError{Code: "not_available", Message: err.Error()}
	}
	if resp.StatusCode != http.StatusOK {
		return computeError(resp.StatusCode, body)
	}
	return (protojson.UnmarshalOptions{DiscardUnknown: true}).Unmarshal(body, response)
}

func computeError(status int, body []byte) error {
	var remote struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	}
	_ = json.Unmarshal(body, &remote)
	code := "internal"
	switch remote.Code {
	case "invalid_argument", "out_of_range", "failed_precondition":
		code = "bad_request"
	case "not_found":
		code = "run_not_found"
	case "permission_denied",
		"unauthenticated",
		"unavailable",
		"resource_exhausted",
		"deadline_exceeded":
		code = "not_available"
	default:
		switch status {
		case http.StatusBadRequest:
			code = "bad_request"
		case http.StatusNotFound:
			code = "run_not_found"
		case http.StatusUnauthorized, http.StatusForbidden, http.StatusTooManyRequests,
			http.StatusBadGateway, http.StatusServiceUnavailable, http.StatusGatewayTimeout:
			code = "not_available"
		}
	}
	if remote.Message == "" {
		remote.Message = fmt.Sprintf("Compute API: HTTP %d %s", status, http.StatusText(status))
	}
	return &QueryError{Code: code, Message: remote.Message}
}

// computeJSON keeps protobuf JSON names, adding nulls
// for fields with presence that protojson omits even with EmitUnpopulated.
func computeJSON(message proto.Message) (map[string]any, error) {
	body, err := (protojson.MarshalOptions{
		UseProtoNames: true, EmitUnpopulated: true,
	}).Marshal(message)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	computeNulls(out, message.ProtoReflect().Descriptor())
	return out, nil
}

func computeNulls(object map[string]any, descriptor protoreflect.MessageDescriptor) {
	fields := descriptor.Fields()
	for i := range fields.Len() {
		field := fields.Get(i)
		name := string(field.Name())
		value, exists := object[name]
		if !exists && field.HasPresence() {
			object[name] = nil
		}
		if field.Message() == nil || field.IsMap() {
			continue
		}
		if field.IsList() {
			for _, entry := range value.([]any) {
				computeNulls(entry.(map[string]any), field.Message())
			}
		} else if nested, ok := value.(map[string]any); ok {
			computeNulls(nested, field.Message())
		}
	}
}

func writeComputeJSON(w io.Writer, verb string, params *RemoteRunParams, out map[string]any) error {
	out["schema"] = "leet.compute." + verb + "/1"
	out["source"] = params.remoteSource(params.RunID)
	out["retrieval_method"] = "api"
	out["truncated"] = false
	out["warnings"] = []string{}
	return encodeJSON(w, out, "")
}
