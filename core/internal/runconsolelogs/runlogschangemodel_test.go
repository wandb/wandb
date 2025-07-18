package runconsolelogs_test

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/terminalemulator"
)

func TestRunLogsLineMarshalJSON(t *testing.T) {
	// Create a fixed timestamp for consistent testing
	fixedTime := time.Date(2023, 4, 5, 10, 15, 30, 0, time.UTC)

	tests := []struct {
		name         string
		input        *RunLogsLine
		expectedJSON string
	}{
		{
			name: "Normal stdout line",
			input: &RunLogsLine{
				LineContent: terminalemulator.LineContent{
					MaxLength: 100,
					Content:   []rune("Hello, world!"),
				},
				StreamPrefix: "",
				Timestamp:    fixedTime,
				StreamLabel:  "",
			},
			expectedJSON: `{"ts":"2023-04-05T10:15:30.000000","content":"Hello, world!"}`,
		},
		{
			name: "Error line with label",
			input: &RunLogsLine{
				LineContent: terminalemulator.LineContent{
					MaxLength: 100,
					Content:   []rune("Division by zero"),
				},
				StreamPrefix: "ERROR ",
				Timestamp:    fixedTime,
				StreamLabel:  "stderr",
			},
			expectedJSON: `{"level":"error","ts":"2023-04-05T10:15:30.000000","label":"stderr","content":"Division by zero"}`,
		},
		{
			name: "Line with special characters",
			input: &RunLogsLine{
				LineContent: terminalemulator.LineContent{
					MaxLength: 100,
					Content:   []rune("Line with \u00A9 and \u2603 symbols"),
				},
				StreamPrefix: "",
				Timestamp:    fixedTime,
				StreamLabel:  "stdout",
			},
			expectedJSON: `{"ts":"2023-04-05T10:15:30.000000","label":"stdout","content":"Line with © and ☃ symbols"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			jsonData, err := json.Marshal(tt.input)
			assert.NoError(t, err)
			assert.Equal(t, tt.expectedJSON, string(jsonData))

			// Verify JSON structure by unmarshaling
			var decoded map[string]any
			err = json.Unmarshal(jsonData, &decoded)
			assert.NoError(t, err)

			// Check specific fields
			if tt.input.StreamPrefix != "" {
				assert.Equal(t, "error", decoded["level"])
			} else {
				_, exists := decoded["level"]
				assert.False(t, exists)
			}

			assert.Equal(t, "2023-04-05T10:15:30.000000", decoded["ts"])
		})
	}
}

func TestLegacyFormat(t *testing.T) {
	// Create a fixed timestamp for consistent testing
	fixedTime := time.Date(2023, 4, 5, 10, 15, 30, 0, time.UTC)

	tests := []struct {
		name     string
		input    *RunLogsLine
		expected string
	}{
		{
			name: "Standard stdout line",
			input: &RunLogsLine{
				LineContent: terminalemulator.LineContent{
					Content: []rune("Regular log message"),
				},
				StreamPrefix: "",
				Timestamp:    fixedTime,
				StreamLabel:  "",
			},
			expected: "2023-04-05T10:15:30.000000 Regular log message",
		},
		{
			name: "Error line with label",
			input: &RunLogsLine{
				LineContent: terminalemulator.LineContent{
					Content: []rune("Critical error occurred"),
				},
				StreamPrefix: "ERROR ",
				Timestamp:    fixedTime,
				StreamLabel:  "stderr",
			},
			expected: "ERROR 2023-04-05T10:15:30.000000 [stderr] Critical error occurred",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.input.LegacyFormat()
			assert.Equal(t, tt.expected, result)
		})
	}
}
