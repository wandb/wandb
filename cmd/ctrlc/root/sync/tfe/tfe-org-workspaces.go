package tfe

import (
	"context"
	"encoding/json"
	"fmt"

	"strconv"

	"github.com/charmbracelet/log"
	"github.com/hashicorp/go-tfe"
)

const (
	Kind = "Workspace"
)

type WorkspaceResource struct {
	Version    string
	Kind       string
	Name       string
	Identifier string
	Config     map[string]string
	Metadata   map[string]string
}

func getLinksMetadata(workspace *tfe.Workspace, baseURL string) *string {
	if workspace.Organization == nil {
		return nil
	}
	links := map[string]string{
		"Terraform Workspace": fmt.Sprintf("%s/app/%s/workspaces/%s", baseURL, workspace.Organization.Name, workspace.Name),
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
		key := fmt.Sprintf("terraform-cloud/tag/%s", tag.Name)
		tags[key] = "true"
	}
	return tags
}

func convertWorkspaceToResource(workspace *tfe.Workspace, baseURL string) (WorkspaceResource, error) {
	if workspace == nil {
		return WorkspaceResource{}, fmt.Errorf("workspace is nil")
	}
	version := workspace.TerraformVersion
	kind := Kind
	name := workspace.Name
	identifier := workspace.ID
	config := map[string]string{
		"workspaceId": workspace.ID,
	}
	metadata := map[string]string{
		"ctrlplane/external-id":                workspace.ID,
		"terraform-cloud/organization":         workspace.Organization.Name,
		"terraform-cloud/workspace-name":       workspace.Name,
		"terraform-cloud/workspace-auto-apply": strconv.FormatBool(workspace.AutoApply),
		"terraform/version":                    workspace.TerraformVersion,
	}

	linksMetadata := getLinksMetadata(workspace, baseURL)
	if linksMetadata != nil {
		metadata["ctrlplane/links"] = *linksMetadata
	}

	variables := getWorkspaceVariables(workspace)
	for key, value := range variables {
		metadata[key] = value
	}

	tags := getWorkspaceTags(workspace)
	for key, value := range tags {
		metadata[key] = value
	}

	vcsRepo := getWorkspaceVcsRepo(workspace)
	for key, value := range vcsRepo {
		metadata[key] = value
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

func getWorkspacesInOrg(client *tfe.Client, organization string) ([]*tfe.Workspace, error) {

	// TODO: use cmd context
	ctx := context.Background()

	items, err := client.Workspaces.List(ctx, organization, &tfe.WorkspaceListOptions{})
	if err != nil {
		return nil, err
	}

	workspaces := items.Items
	return workspaces, nil
}
