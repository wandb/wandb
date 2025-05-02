package api

import (
	"context"
	"fmt"
	"net/http"

	"github.com/charmbracelet/log"
)

func NewResourceProvider(client *ClientWithResponses, workspaceId string, name string) (*ResourceProvider, error) {
	log.Debug("Upserting resource provider", "workspaceId", workspaceId, "name", name)
	ctx := context.Background()

	log.Debug("Upserting resource provider", "workspaceId", workspaceId, "name", name)
	resp, err := client.UpsertResourceProviderWithResponse(
		ctx, workspaceId, name)
	if err != nil {
		log.Error("Failed to upsert resource provider",
			"error", err,
			"workspaceId", workspaceId,
			"name", name,
			"status", resp.StatusCode,
			"body", string(resp.Body))
		return nil, fmt.Errorf("failed to upsert resource provider: %w", err)
	}

	log.Debug("Got response from upserting resource provider",
		"status", resp.StatusCode,
		"body", string(resp.Body))

	if resp.JSON200 == nil {
		log.Error("Invalid response from upserting resource provider",
			"status", resp.StatusCode(),
			"body", string(resp.Body))
		return nil, fmt.Errorf("failed to upsert resource provider: %s", string(resp.Body))
	}

	provider := resp.JSON200
	log.Debug("Successfully created resource provider",
		"id", provider.Id,
		"name", provider.Name)

	return &ResourceProvider{
		Name:   provider.Name,
		ID:     provider.Id,
		client: client,
		workspaceId: workspaceId,
	}, nil
}

type ResourceProvider struct {
	ID          string
	Name        string
	client      *ClientWithResponses
	workspaceId string
}

type AgentResource struct {
	Config     map[string]interface{} `json:"config"`
	Identifier string                 `json:"identifier"`
	Kind       string                 `json:"kind"`
	Metadata   map[string]string      `json:"metadata"`
	Name       string                 `json:"name"`
	Version    string                 `json:"version"`
}

func (r *ResourceProvider) UpsertResource(ctx context.Context, resources []AgentResource) (*http.Response, error) {
	apiResources := make([]struct {
		Config     map[string]interface{} `json:"config"`
		Identifier string                 `json:"identifier"`
		Kind       string                 `json:"kind"`
		Metadata   map[string]string      `json:"metadata"`
		Name       string                 `json:"name"`
		Version    string                 `json:"version"`
	}, len(resources))

	for i, resource := range resources {
		apiResources[i] = struct {
			Config     map[string]interface{} `json:"config"`
			Identifier string                 `json:"identifier"`
			Kind       string                 `json:"kind"`
			Metadata   map[string]string      `json:"metadata"`
			Name       string                 `json:"name"`
			Version    string                 `json:"version"`
		}{
			Config:     resource.Config,
			Identifier: resource.Identifier,
			Kind:       resource.Kind,
			Metadata:   resource.Metadata,
			Name:       resource.Name,
			Version:    resource.Version,
		}
	}

	resp, err := r.client.SetResourceProvidersResources(
		ctx,
		r.ID,
		SetResourceProvidersResourcesJSONRequestBody{
			Resources: apiResources,
		},
	)

	return resp, err
}

func (r *ResourceProvider) AddResourceRelationshipRule(ctx context.Context, rules []CreateResourceRelationshipRule) error {
	for _, rule := range rules {
		rule.WorkspaceId = r.workspaceId
		resp, err := r.client.UpsertResourceRelationshipRuleWithResponse(ctx, rule)
		if err != nil {
			return err
		}
		if resp.StatusCode() != http.StatusOK {
			return fmt.Errorf("failed to upsert resource relationship rule: %s", string(resp.Body))
		}
	}
	return nil
}
