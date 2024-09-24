package artifacts

import (
	"context"
	"fmt"
	"slices"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/gqlprobe"
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

	if IsArtifactRegistryProject(portfolioProject) {
		orgFieldNames, err := gqlprobe.GetGraphQLFields(al.Ctx, al.GraphqlClient, "Organization")
		if err != nil {
			return err
		}
		switch {
		case slices.Contains(orgFieldNames, "orgEntity"):
			response, err := gql.FetchOrgEntityFromEntity(
				al.Ctx,
				al.GraphqlClient,
				portfolioEntity,
			)
			if err != nil {
				return err
			}
			if response == nil {
				return fmt.Errorf("Unable to find organization for artifact entity: %s", portfolioEntity)
			}

			// Validate organization inputted by user
			if organization != "" && (organization != response.Entity.Organization.Name && organization != response.Entity.Organization.OrgEntity.Name) {
				return fmt.Errorf("Wrong organization: %s for registry: %s", organization, portfolioProject)
			}
			portfolioEntity = response.Entity.Organization.OrgEntity.Name
		case organization == "":
			// User is trying to shorthand path but server isn't upgraded to handle it
			// TODO: good error message
			return fmt.Errorf("Upgrade server to about xx to shorthand Registry path")
		default:
			// Use traditional registry path with org entity if server doesn't support it
			portfolioEntity = organization
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
	var err error
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
