package wbapi

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// AuthHandler responds to authentication-related API requests.
type AuthHandler struct {
	graphqlClient      graphql.Client
	credentialProvider api.CredentialProvider
}

func NewAuthHandler(
	graphqlClient graphql.Client,
	credentialProvider api.CredentialProvider,
) *AuthHandler {
	return &AuthHandler{
		graphqlClient:      graphqlClient,
		credentialProvider: credentialProvider,
	}
}

// HandleRequest routes an AuthRequest to the handler for its subrequest.
func (h *AuthHandler) HandleRequest(
	ctx context.Context,
	request *spb.AuthRequest,
) *spb.ApiResponse {
	switch request.Request.(type) {
	case *spb.AuthRequest_AuthenticateRequest:
		return h.HandleAuthenticate(ctx, request.GetAuthenticateRequest())
	case *spb.AuthRequest_GetAccessTokenRequest:
		return h.HandleGetAccessToken(ctx, request.GetGetAccessTokenRequest())
	default:
		return apiErrorResponse(
			fmt.Sprintf("unsupported auth request type: %T", request.Request), 0)
	}
}

// HandleAuthenticate verifies the account credentials.
//
// The credentials come from the settings used to initialize the API
// instance: an API key, or an identity token file when using federated
// identity. Both are applied by the credential provider attached to the
// GraphQL client, so this handler works the same for either method.
func (h *AuthHandler) HandleAuthenticate(
	ctx context.Context,
	request *spb.AuthenticateRequest,
) *spb.ApiResponse {
	data, err := gql.Viewer(ctx, h.graphqlClient)

	// The credentials are valid exactly if the server resolved a viewer.
	//
	// Field-level GraphQL errors (like a failing resolver for one of the
	// requested fields) do not invalidate the credentials, so partial data
	// is accepted as long as the viewer itself is present. Any field,
	// including the entity, may be null for unusual accounts and old
	// server versions.
	if data == nil || data.GetViewer() == nil {
		if err != nil {
			message, status := graphqlErrorInfo(err)
			return apiErrorResponse(message, status)
		}
		return apiErrorResponse(
			"invalid credentials: the server did not recognize an account"+
				" for the configured credentials",
			0,
		)
	}

	viewer := data.GetViewer()
	response := &spb.AuthenticateResponse{}
	if entity := viewer.GetEntity(); entity != nil {
		response.DefaultEntity = *entity
	}
	if username := viewer.GetUsername(); username != nil {
		response.Username = *username
	}
	if email := viewer.GetEmail(); email != nil {
		response.Email = *email
	}
	if flags := viewer.GetFlags(); flags != nil {
		response.FlagsJson = *flags
	}
	if teams := viewer.GetTeams(); teams != nil {
		for _, edge := range teams.GetEdges() {
			if node := edge.GetNode(); node != nil {
				response.Teams = append(response.Teams, node.GetName())
			}
		}
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_AuthResponse{
			AuthResponse: &spb.AuthResponse{
				Response: &spb.AuthResponse_AuthenticateResponse{
					AuthenticateResponse: response,
				},
			},
		},
	}
}

// HandleGetAccessToken returns the access token for the API instance's
// credentials.
//
// A token exists only when using federated identity, in which case the
// credential provider exchanges the configured identity token for an
// access token, caching it in the credentials file and refreshing it when
// it is at or near expiration. For other credential types, the response
// contains an empty access token.
func (h *AuthHandler) HandleGetAccessToken(
	ctx context.Context,
	_ *spb.GetAccessTokenRequest,
) *spb.ApiResponse {
	response := &spb.GetAccessTokenResponse{}

	if provider, ok := h.credentialProvider.(api.AccessTokenProvider); ok {
		token, err := provider.AccessToken(ctx)
		if err != nil {
			return apiErrorResponse(err.Error(), 0)
		}
		response.AccessToken = token
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_AuthResponse{
			AuthResponse: &spb.AuthResponse{
				Response: &spb.AuthResponse_GetAccessTokenResponse{
					GetAccessTokenResponse: response,
				},
			},
		},
	}
}
