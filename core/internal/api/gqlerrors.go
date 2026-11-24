package api

import (
	"encoding/json"
	"fmt"
	"net/http"
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

	return extractGQLErrors(gqlResponse)
}

// FormatGQLErrors returns the user message for a GraphQL error.
//
// If the error response includes an "errors" field, the errors are joined
// into one string. Otherwise, it returns a non-empty string with the HTTP
// status code and description.
//
// Never returns an empty string. This is important because some legacy Python
// code treats an empty error message as "no error".
func FormatGQLErrors(err *graphql.HTTPError) string {
	if message := extractGQLErrors(err.Response); message != "" {
		return message
	} else {
		return fmt.Sprintf(
			"<HTTP status %d %q>",
			err.StatusCode,
			http.StatusText(err.StatusCode),
		)
	}
}

// extractGQLErrors returns the error messages in a graphql.Response
// combined into one string.
//
// Returns the empty string if there are no errors.
func extractGQLErrors(response graphql.Response) string {
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
