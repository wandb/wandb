package cliutil

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"text/template"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

// HandleResponseOutput processes the HTTP response and passes the decoded result to HandleResponseOutput
func HandleResponseOutput(cmd *cobra.Command, resp *http.Response) error {
	defer resp.Body.Close()

	intervalFlag, _ := cmd.Flags().GetString("interval")
	if intervalFlag != "" {
		return nil
	}

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

	return HandleOutput(cmd, result)
}

// HandleResponseOutput processes the result map and outputs it according to the template or format flag
func HandleOutput(cmd *cobra.Command, result map[string]interface{}) error {
	templateFlag, _ := cmd.Flags().GetString("template")
	formatFlag, _ := cmd.Flags().GetString("format")

	if templateFlag != "" {
		tmpl, err := template.New("output").Parse(templateFlag)
		if err != nil {
			return fmt.Errorf("failed to parse template: %w", err)
		}

		if err := tmpl.Execute(cmd.OutOrStdout(), result); err != nil {
			return fmt.Errorf("failed to execute template: %w", err)
		}
		fmt.Fprintln(cmd.OutOrStdout())
		return nil
	}

	var output []byte
	var err error

	switch formatFlag {
	case "yaml":
		output, err = yaml.Marshal(result)
		if err != nil {
			return fmt.Errorf("failed to marshal to YAML: %w", err)
		}
	case "github-action":
		return handleGitHubActionOutput(cmd, result)
	default:
		output, err = json.MarshalIndent(result, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal to JSON: %w", err)
		}
	}

	fmt.Fprintln(cmd.OutOrStdout(), string(output))
	return nil
}

func handleGitHubActionOutput(cmd *cobra.Command, result map[string]interface{}) error {
	writer, err := NewGitHubOutputWriter()
	if err != nil {
		return fmt.Errorf("failed to create GitHubOutputWriter: %w", err)
	}
	defer writer.Close()

	output, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("failed to marshal to JSON: %w", err)
	}

	writer.Write("json", string(output))
	var data map[string]interface{}
	if err := json.Unmarshal(output, &data); err != nil {
		return fmt.Errorf("failed to unmarshal JSON: %w", err)
	}

	var flatten func(prefix string, v interface{}) error
	flatten = func(prefix string, v interface{}) error {
		switch val := v.(type) {
		case map[string]interface{}:
			for k, v := range val {
				newPrefix := strings.ReplaceAll(k, "/", "_")
				if prefix != "" {
					newPrefix = prefix + "_" + newPrefix
				}
				if err := flatten(newPrefix, v); err != nil {
					return err
				}
			}
		case []interface{}:
			for i, v := range val {
				newPrefix := fmt.Sprintf("%s_%d", prefix, i)
				if err := flatten(newPrefix, v); err != nil {
					return err
				}
			}
		default:
			if val == nil {
				return nil
			}

			fmt.Fprintln(cmd.OutOrStdout(), prefix, "=", fmt.Sprintf("%v", val))
			writer.Write(prefix, fmt.Sprintf("%v", val))
		}
		return nil
	}

	if err := flatten("", data); err != nil {
		return fmt.Errorf("failed to flatten output: %w", err)
	}

	return nil
}

// GitHubOutputWriter is a helper for writing to the GITHUB_OUTPUT file.
type GitHubOutputWriter struct {
	file *os.File
}

// NewGitHubOutputWriter creates and initializes a new GitHubOutputWriter. It
// opens the GITHUB_OUTPUT file for appending.
func NewGitHubOutputWriter() (*GitHubOutputWriter, error) {
	// Get the GITHUB_OUTPUT environment variable
	githubOutput := os.Getenv("GITHUB_OUTPUT")
	if githubOutput == "" {
		return nil, fmt.Errorf("GITHUB_OUTPUT environment variable is not set")
	}

	// Open the file in append mode
	file, err := os.OpenFile(githubOutput, os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return nil, fmt.Errorf("error opening GITHUB_OUTPUT file: %w", err)
	}

	return &GitHubOutputWriter{file: file}, nil
}

// Write writes a key-value pair to the GITHUB_OUTPUT file.
func (w *GitHubOutputWriter) Write(key, value string) error {
	if w.file == nil {
		return fmt.Errorf("GitHubOutputWriter is not initialized")
	}

	// Format and write the output
	output := fmt.Sprintf("%s=%s\n", key, value)
	if _, err := w.file.WriteString(output); err != nil {
		return fmt.Errorf("error writing to GITHUB_OUTPUT file: %w", err)
	}

	return nil
}

// Close closes the GITHUB_OUTPUT file.
func (w *GitHubOutputWriter) Close() error {
	if w.file == nil {
		return nil
	}
	err := w.file.Close()
	w.file = nil
	return err
}

// GetEnv fetches the value of an environment variable or returns a default
// value.
func GetEnv(key string, defaultValue string) string {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}
	return value
}
