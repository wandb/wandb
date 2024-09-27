package server_test

import (
	"context"
	"testing"

	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/pkg/artifacts"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var validFetchOrgEntityFromEntityResponse = `{
				"entity": {
					"organization": {
						"name": "orgName",
						"orgEntity": {
							"name": "orgEntityName_123"
						}
					}
				}
			}`

func TestLinkRegistryArtifact(t *testing.T) {
	registryProject := artifacts.RegistryProjectPrefix + "projectName"
	expectLinkArtifactFailure := "expect link artifact to fail, wrong org entity"

	testCases := []struct {
		name              string
		inputOrganization string
		isOldServer       bool
		errorMessage      string
	}{
		{"Link registry artifact with orgName updated server", "orgName", false, ""},
		{"Link registry artifact with orgName old server", "orgName", true, expectLinkArtifactFailure},
		{"Link registry artifact with orgEntity name updated server", "orgEntityName_123", false, ""},
		{"Link registry artifact with orgEntity name old server", "orgEntityName_123", true, ""},
		{"Link registry artifact with short hand path updated server", "", false, ""},
		{"Link registry artifact with short hand path old server", "", true, "Upgrade server"},
		{"Link with wrong org/orgEntity name with updated server", "potato", false, "Wrong organization"},
		{"Link with wrong org/orgEntity name with updated server", "potato", true, expectLinkArtifactFailure},
	}
	for _, tc := range testCases {
		mockGQL := gqlmock.NewMockClient()

		newLinker := func(req *spb.LinkArtifactRequest) *artifacts.ArtifactLinker {
			return &artifacts.ArtifactLinker{
				Ctx:           context.Background(),
				LinkArtifact:  req,
				GraphqlClient: mockGQL,
			}
		}

		// If user is on old server, we can't fetch the org entity name so just directly call link artifact
		numExpectedRequests := 3
		if tc.isOldServer {
			numExpectedRequests = 2
		}

		t.Run("Link registry artifact with orgName updated server", func(t *testing.T) {
			req := &spb.LinkArtifactRequest{
				ClientId:              "clientId123",
				PortfolioName:         "portfolioName",
				PortfolioEntity:       "entityName",
				PortfolioProject:      registryProject,
				PortfolioAliases:      nil,
				PortfolioOrganization: tc.inputOrganization,
			}

			var validTypeFieldsResponse string
			if tc.isOldServer {
				validTypeFieldsResponse = `{"TypeInfo": {"fields": []}}`
			} else {
				validTypeFieldsResponse = `{
					"TypeInfo": {
						"fields": [{"name": "orgEntity"}]
					}
				}`
			}
			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("TypeFields"),
				validTypeFieldsResponse,
			)

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("LinkArtifact"),
				validLinkArtifactResponse,
			)

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("FetchOrgEntityFromEntity"),
				validFetchOrgEntityFromEntityResponse,
			)

			linker := newLinker(req)
			err := linker.Link()
			if err != nil {
				assert.NotEmpty(t, tc.errorMessage)
				assert.ErrorContainsf(t, err, tc.errorMessage, "Expected error containing: %s", tc.errorMessage)
				return
			}

			// This error is not triggered by Link() because its linkArtifact that fails and we aren't actually calling it
			// Here we are checking that the org entity being passed into linkArtifact is wrong so we know the query will fail
			if tc.errorMessage == expectLinkArtifactFailure {
				requests := mockGQL.AllRequests()
				assert.Len(t, requests, numExpectedRequests)

				// Confirms that the request is incorrectly put into link artifact graphql request
				gqlmock.AssertRequest(t,
					gqlmock.WithVariables(
						gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
						// Here the entity name is not orgEntityName_123 and this will fail if actually called
						gqlmock.GQLVar("entityName", gomock.Not(gomock.Eq("orgEntityName_123"))),
						gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
						gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
						gqlmock.GQLVar("artifactId", gomock.Nil()),
					),
					requests[numExpectedRequests-1])
			} else {
				// If no error, check that we are passing in the correct org entity name into linkArtifact
				assert.Empty(t, tc.errorMessage)
				assert.NoError(t, err)
				requests := mockGQL.AllRequests()
				assert.Len(t, requests, numExpectedRequests)

				gqlmock.AssertRequest(t,
					gqlmock.WithVariables(
						gqlmock.GQLVar("projectName", gomock.Eq(registryProject)),
						gqlmock.GQLVar("entityName", gomock.Eq("orgEntityName_123")),
						gqlmock.GQLVar("artifactPortfolioName", gomock.Eq("portfolioName")),
						gqlmock.GQLVar("clientId", gomock.Eq("clientId123")),
						gqlmock.GQLVar("artifactId", gomock.Nil()),
					),
					requests[numExpectedRequests-1])
			}
		})
	}
}
