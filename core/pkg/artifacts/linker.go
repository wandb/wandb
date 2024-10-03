package artifacts

import (
	"context"
	"fmt"
	"slices"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type ArtifactLinker struct {
	Ctx           context.Context
	Logger        *observability.CoreLogger
	LinkArtifact  *spb.LinkArtifactRequest
	GraphqlClient graphql.Client
}

func (al *ArtifactLinker) Link() error {
	clientId := al.LinkArtifact.ClientId
	serverId := al.LinkArtifact.ServerId
	portfolioName := al.LinkArtifact.PortfolioName
	portfolioEntity := al.LinkArtifact.PortfolioEntity
	portfolioProject := al.LinkArtifact.PortfolioProject
	organization := al.LinkArtifact.PortfolioOrganization
	var portfolioAliases []gql.ArtifactAliasInput

	var err error
	if IsArtifactRegistryProject(portfolioProject) {
		portfolioEntity, err = al.resolveOrgEntityName(portfolioEntity, organization)
		if err != nil {
			return err
		}
	}

	for _, alias := range al.LinkArtifact.PortfolioAliases {
		portfolioAliases = append(portfolioAliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: portfolioName,
				Alias:                  alias,
			},
		)
	}
	switch {
	case serverId != "":
		_, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolioName,
			portfolioEntity,
			portfolioProject,
			portfolioAliases,
			nil,
			&serverId,
		)
	case clientId != "":
		_, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolioName,
			portfolioEntity,
			portfolioProject,
			portfolioAliases,
			&clientId,
			nil,
		)
	default:
		err = fmt.Errorf("artifact must have either server id or client id")
	}

	if err != nil {
		err = fmt.Errorf(
			"LinkArtifact: %s, error: %w",
			portfolioName,
			err,
		)
	}

	return err
}

func (al *ArtifactLinker) resolveOrgEntityName(portfolioEntity string, organization string) (string, error) {
	// Fetches the org entity of the portfolio entity to
	// 1. validate the user inputted the correct display org name or org entity name and
	// 2. return the org entity name so we can use the correct entity name to link the artifact.
	orgFieldNames, err := GetGraphQLFields(al.Ctx, al.GraphqlClient, "Organization")
	if err != nil {
		return "", err
	}
	canFetchOrgEntity := slices.Contains(orgFieldNames, "orgEntity")
	if organization == "" && !canFetchOrgEntity {
		return "", fmt.Errorf("Fetching Registry artifacts without inputting an organization is unavailable for your server version. Please upgrade your server to 0.50.0 or later.")
	}
	if !canFetchOrgEntity {
		// Use traditional registry path with org entity if server doesn't support it
		return organization, nil
	}

	response, err := gql.FetchOrgEntityFromEntity(
		al.Ctx,
		al.GraphqlClient,
		portfolioEntity,
	)
	if err != nil {
		return "", err
	}
	if response == nil || response.GetEntity() == nil || response.GetEntity().GetOrganization() == nil || response.GetEntity().GetOrganization().GetOrgEntity() == nil {
		return "", fmt.Errorf("Unable to find organization for artifact under entity: %s. Please make sure you are using a team entity when linking to the Registry", portfolioEntity)
	}

	// Validate organization inputted by user
	orgEntityName := response.Entity.Organization.OrgEntity.Name
	inputOrgMatchesOrgNameOrOrgEntityName := (organization == orgEntityName || organization == response.Entity.Organization.Name)
	if organization != "" && !inputOrgMatchesOrgNameOrOrgEntityName {
		return "", fmt.Errorf("Artifact belongs to the organization %s and cannot be linked to %s. Please update the target path with the correct organization name.", orgEntityName, organization)
	}
	return orgEntityName, nil
}
