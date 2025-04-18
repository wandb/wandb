package api_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/api"
)

func TestUnknownFormat(t *testing.T) {
	unknownFormats := []string{
		"not JSON",
		`"JSON string"`,
		`{"unknownField": 123}`,
		`{"error": 123}`,
		`{"errors": 123}`,
		`{"errors": "string"}`,
	}

	for _, format := range unknownFormats {
		t.Run(format, func(t *testing.T) {
			assert.Empty(t, api.ErrorFromWBResponse([]byte(format)))
		})
	}
}

func TestKnownFormat(t *testing.T) {
	type testCase struct {
		body    string
		message string
	}

	testCases := []testCase{
		{`{"error": "string"}`, "string"},
		{`{"error": {"message": "string"}}`, "string"},
		{`{"errors": ["string1", {"message": "string2"}]}`, "string1; string2"},
	}

	for _, testCase := range testCases {
		t.Run(testCase.body, func(t *testing.T) {
			assert.Equal(t,
				testCase.message,
				api.ErrorFromWBResponse([]byte(testCase.body)))
		})
	}
}
