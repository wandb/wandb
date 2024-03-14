package artifacts

import (
	"context"
	"errors"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/gqltest"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestArtifactLinker_Link(t *testing.T) {
	tests := []struct {
		name        string
		linkRecord  *service.LinkArtifactRecord
		response    *gql.LinkArtifactResponse
		expectedErr error
		expectPanic bool
	}{
		{
			name: "successful link with server ID",
			linkRecord: &service.LinkArtifactRecord{
				ServerId:         "server123",
				PortfolioName:    "portfolio1",
				PortfolioEntity:  "entity1",
				PortfolioProject: "project1",
			},
			response:    &gql.LinkArtifactResponse{},
			expectedErr: nil,
			expectPanic: false,
		},
		{
			name: "successful link with client ID",
			linkRecord: &service.LinkArtifactRecord{
				ClientId:         "client123",
				PortfolioName:    "portfolio2",
				PortfolioEntity:  "entity2",
				PortfolioProject: "project2",
			},
			response:    &gql.LinkArtifactResponse{},
			expectedErr: nil,
			expectPanic: false,
		},
		{
			name: "error when both server and client ID are empty",
			linkRecord: &service.LinkArtifactRecord{
				PortfolioName:    "portfolio3",
				PortfolioEntity:  "entity3",
				PortfolioProject: "project3",
			},
			response:    nil,
			expectedErr: errors.New("LinkArtifact: portfolio3, error: artifact must have either server id or client id"),
			expectPanic: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			defer ctrl.Finish()

			mockClient := gqltest.NewMockClient(ctrl)
			if tt.expectedErr == nil {
				mockClient.EXPECT().MakeRequest(gomock.Any(), gomock.Any(), gomock.Any()).Return(nil)
			}

			linker := &ArtifactLinker{
				Ctx:           context.Background(),
				Logger:        observability.NewNoOpLogger(),
				LinkArtifact:  tt.linkRecord,
				GraphqlClient: mockClient,
			}

			if tt.expectPanic {
				assert.PanicsWithError(t, tt.expectedErr.Error(), func() {
					_ = linker.Link()
				})
			} else {
				err := linker.Link()
				assert.NoError(t, err)
			}
		})
	}
}
