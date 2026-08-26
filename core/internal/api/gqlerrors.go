package api

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
)

// MaybeGQLErrorResponse parses and returns the GraphQL error messages from
// the HTTP response body, if it looks like a GraphQL error response.
func MaybeGQLErrorResponse(responseBody []byte) string {
	var gqlResponse graphql.Response
	err := json.Unmarshal(responseBody, &gqlResponse)
	if err != nil {
		return ""
	}

	return FormatGQLErrors(gqlResponse)
}

// FormatGQLErrors formats the error messages in a graphql.Response.
//
// Returns the empty string if there are no errors.
func FormatGQLErrors(response graphql.Response) string {
	switch {
	case len(response.Errors) < 1:
		return ""

	case len(response.Errors) == 1:
		return response.Errors[0].Message

	default:
		var messages []string
		for _, err := range response.Errors {
			messages = append(messages, err.Message)
		}
		joinedMessages := strings.Join(messages, "; ")
		return fmt.Sprintf("[%s]", joinedMessages)
	}
}
