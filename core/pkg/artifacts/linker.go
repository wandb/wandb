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

func (al *ArtifactLinker) Link() (response *gql.LinkArtifactResponse, err error) {
	clientId := al.LinkArtifact.ClientId
	serverId := al.LinkArtifact.ServerId
	portfolioName := al.LinkArtifact.PortfolioName
	portfolioEntity := al.LinkArtifact.PortfolioEntity
	portfolioProject := al.LinkArtifact.PortfolioProject
	organization := al.LinkArtifact.PortfolioOrganization
	var portfolioAliases []gql.ArtifactAliasInput

	if IsArtifactRegistryProject(portfolioProject) {
		portfolioEntity, err = al.resolveOrgEntityName(portfolioEntity, organization)
		if err != nil {
			return nil, err
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
		response, err = gql.LinkArtifact(
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
		response, err = gql.LinkArtifact(
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
		return nil, err
	}
	return response, nil
}

// resolveOrgEntityName fetches the portfolio's org entity's name.
//
// The organization parameter may be empty, an org's display name, or an org entity name.
//
// If the server doesn't support fetching the org name of a portfolio, then this returns
// the organization parameter, or an error if it is empty. Otherwise, this returns the
// fetched value after validating that the given organization, if not empty, matches
// either the org's display or entity name.
func (al *ArtifactLinker) resolveOrgEntityName(portfolioEntity string, organization string) (string, error) {
	orgFieldNames, err := GetGraphQLFields(al.Ctx, al.GraphqlClient, "Organization")
	if err != nil {
		return "", err
	}
	canFetchOrgEntity := slices.Contains(orgFieldNames, "orgEntity")
	if organization == "" && !canFetchOrgEntity {
		// Support is added in version 0.50.0 of the wandb server.
		return "", fmt.Errorf("fetching Registry artifacts unsupported and no organization given")
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
	if response == nil ||
		response.GetEntity() == nil ||
		response.GetEntity().GetOrganization() == nil ||
		response.GetEntity().GetOrganization().GetOrgEntity() == nil {
		return "", fmt.Errorf("unable to resolve an organization associated with the entity: %s "+
			"that is initialized in the API or Run settings. This could be because %s is a personal entity or "+
			"the team entity doesn't exist. "+
			"Please re-initialize the API or Run with a team entity using "+
			"wandb.Api(overrides={'entity': '<my_team_entity>'}) "+
			"or wandb.init(entity='<my_team_entity>')",
			portfolioEntity, portfolioEntity)
	}

	// Validate organization inputted by user
	orgEntityName := response.Entity.Organization.OrgEntity.Name
	orgDisplayName := response.Entity.Organization.Name
	inputMatchesOrgName := organization == orgDisplayName
	inputMatchesOrgEntityName := organization == orgEntityName
	if organization != "" && !inputMatchesOrgName && !inputMatchesOrgEntityName {
		return "", fmt.Errorf("artifact belongs to the organization %q and cannot be linked/fetched with %q. "+
			"Please update the target path with the correct organization name", orgDisplayName, organization)
	}
	return orgEntityName, nil
}
