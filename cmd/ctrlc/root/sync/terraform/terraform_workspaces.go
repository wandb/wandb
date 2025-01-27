package terraform

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"time"

	"strconv"

	"github.com/avast/retry-go"
	"github.com/charmbracelet/log"
	"github.com/hashicorp/go-tfe"
)

const (
	Kind    = "Workspace"
	Version = "terraform/v1"
)

type WorkspaceResource struct {
	Config     map[string]interface{}
	Identifier string
	Kind       string
	Metadata   map[string]string
	Name       string
	Version    string
}

func getLinksMetadata(workspace *tfe.Workspace, baseURL url.URL) *string {
	if workspace.Organization == nil {
		return nil
	}
	links := map[string]string{
		"Terraform Workspace": fmt.Sprintf("%s/app/%s/workspaces/%s", baseURL.String(), workspace.Organization.Name, workspace.Name),
	}
	linksJSON, err := json.Marshal(links)
	if err != nil {
		log.Error("Failed to marshal links", "error", err)
		return nil
	}
	linksString := string(linksJSON)
	return &linksString
}

func getWorkspaceVariables(workspace *tfe.Workspace) map[string]string {
	variables := make(map[string]string)
	for _, variable := range workspace.Variables {
		if variable != nil && variable.Category == tfe.CategoryTerraform && !variable.Sensitive {
			key := fmt.Sprintf("terraform-cloud/variables/%s", variable.Key)
			variables[key] = variable.Value
		}
	}
	return variables
}

func getWorkspaceVcsRepo(workspace *tfe.Workspace) map[string]string {
	vcsRepo := make(map[string]string)
	if workspace.VCSRepo != nil {
		vcsRepo["terraform-cloud/vcs-repo/identifier"] = workspace.VCSRepo.Identifier
		vcsRepo["terraform-cloud/vcs-repo/branch"] = workspace.VCSRepo.Branch
		vcsRepo["terraform-cloud/vcs-repo/repository-http-url"] = workspace.VCSRepo.RepositoryHTTPURL
	}
	return vcsRepo
}

func getWorkspaceTags(workspace *tfe.Workspace) map[string]string {
	tags := make(map[string]string)
	for _, tag := range workspace.Tags {
		if tag != nil {
			key := fmt.Sprintf("terraform-cloud/tag/%s", tag.Name)
			tags[key] = "true"
		}
	}
	return tags
}

func convertWorkspaceToResource(workspace *tfe.Workspace, baseURL url.URL) (WorkspaceResource, error) {
	if workspace == nil {
		return WorkspaceResource{}, fmt.Errorf("workspace is nil")
	}
	version := Version
	kind := Kind
	name := workspace.Name
	identifier := workspace.ID
	config := map[string]interface{}{
		"workspaceId": workspace.ID,
	}
	metadata := map[string]string{
		"ctrlplane/external-id":                workspace.ID,
		"terraform-cloud/workspace-name":       workspace.Name,
		"terraform-cloud/workspace-auto-apply": strconv.FormatBool(workspace.AutoApply),
		"terraform/version":                    workspace.TerraformVersion,
	}

	if workspace.Organization != nil {
		metadata["terraform-cloud/organization"] = workspace.Organization.Name
	}

	linksMetadata := getLinksMetadata(workspace, baseURL)
	if linksMetadata != nil {
		metadata["ctrlplane/links"] = *linksMetadata
	}

	moreValues := []map[string]string{
		getWorkspaceVariables(workspace),
		getWorkspaceTags(workspace),
		getWorkspaceVcsRepo(workspace),
	}

	for _, moreValue := range moreValues {
		for key, value := range moreValue {
			metadata[key] = value
		}
	}

	return WorkspaceResource{
		Version:    version,
		Kind:       kind,
		Name:       name,
		Identifier: identifier,
		Config:     config,
		Metadata:   metadata,
	}, nil
}

func listWorkspacesWithRetry(ctx context.Context, client *tfe.Client, organization string, pageNum, pageSize int) (*tfe.WorkspaceList, error) {
	var workspaces *tfe.WorkspaceList
	err := retry.Do(
		func() error {
			var err error
			workspaces, err = client.Workspaces.List(ctx, organization, &tfe.WorkspaceListOptions{
				ListOptions: tfe.ListOptions{
					PageNumber: pageNum,
					PageSize:   pageSize,
				},
			})
			return err
		},
		retry.Attempts(5),
		retry.Delay(time.Second),
		retry.MaxDelay(5*time.Second),
	)
	return workspaces, err
}

func listAllWorkspaces(ctx context.Context, client *tfe.Client, organization string) ([]*tfe.Workspace, error) {
	var allWorkspaces []*tfe.Workspace
	pageNum := 1
	pageSize := 100

	for {
		workspaces, err := listWorkspacesWithRetry(ctx, client, organization, pageNum, pageSize)
		if err != nil {
			return nil, fmt.Errorf("failed to list workspaces: %w", err)
		}

		allWorkspaces = append(allWorkspaces, workspaces.Items...)
		if len(workspaces.Items) < pageSize {
			break
		}
		pageNum++
	}

	return allWorkspaces, nil
}

func getWorkspacesInOrg(ctx context.Context, client *tfe.Client, organization string) ([]WorkspaceResource, error) {
	workspaces, err := listAllWorkspaces(ctx, client, organization)
	if err != nil {
		return nil, err
	}

	workspaceResources := []WorkspaceResource{}
	for _, workspace := range workspaces {
		workspaceResource, err := convertWorkspaceToResource(workspace, client.BaseURL())
		if err != nil {
			log.Error("Failed to convert workspace to resource", "error", err, "workspace", workspace.Name)
			continue
		}
		workspaceResources = append(workspaceResources, workspaceResource)
	}
	return workspaceResources, nil
}
