package cliutil

import (
	"encoding/json"
	"fmt"
	"net/http"
	"text/template"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

// HandleOutput processes the API response and outputs it according to the
// template or format flag
func HandleOutput(cmd *cobra.Command, resp *http.Response) error {
	defer resp.Body.Close()

	templateFlag, _ := cmd.Flags().GetString("template")
	formatFlag, _ := cmd.Flags().GetString("format")

	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("failed to decode response: %w", err)
	}

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
	default:
		output, err = json.MarshalIndent(result, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal to JSON: %w", err)
		}
	}

	fmt.Fprintln(cmd.OutOrStdout(), string(output))
	return nil
}
