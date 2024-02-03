package artifacts

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type ArtifactLinker struct {
	Ctx           context.Context
	Logger        *observability.CoreLogger
	LinkArtifact  *service.LinkArtifactRequest
	GraphqlClient graphql.Client
}

func (al *ArtifactLinker) Link() error {
	client_id := al.LinkArtifact.ClientId
	server_id := al.LinkArtifact.ServerId
	portfolio_name := al.LinkArtifact.PortfolioName
	portfolio_entity := al.LinkArtifact.PortfolioEntity
	portfolio_project := al.LinkArtifact.PortfolioProject
	portfolio_aliases := []gql.ArtifactAliasInput{}

	for _, alias := range al.LinkArtifact.PortfolioAliases {
		portfolio_aliases = append(portfolio_aliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: portfolio_name,
				Alias:                  alias,
			},
		)
	}
	var err error
	switch {
	case server_id != "":
		_, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolio_name,
			portfolio_entity,
			portfolio_project,
			portfolio_aliases,
			nil,
			&server_id,
		)
	case client_id != "":
		_, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolio_name,
			portfolio_entity,
			portfolio_project,
			portfolio_aliases,
			&client_id,
			nil,
		)
	default:
		err = fmt.Errorf("LinkArtifact: %s, error: artifact must have either server id or client id", portfolio_name)
		al.Logger.CaptureError("linkArtifact", err)
	}
	if err != nil {
		err = fmt.Errorf("LinkArtifact: %w", err)
		al.Logger.CaptureError("linkArtifact", err)
		return err
	}
	return err
}
