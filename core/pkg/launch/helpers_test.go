package launch

import (
	"os"
	"reflect"
	"testing"
)

func TestFilterDataStructure(t *testing.T) {
	tests := []struct {
		name       string
		ds         map[string]interface{}
		keys       []string
		filterIn   bool
		wantResult map[string]interface{}
	}{
		{
			name: "FilterOutSingleKey",
			ds: map[string]interface{}{
				"config": "value1",
				"data":   "value2",
			},
			keys:       []string{"config"},
			filterIn:   false,
			wantResult: map[string]interface{}{"data": "value2"},
		},
		{
			name: "FilterOutNestedKey",
			ds: map[string]interface{}{
				"config": map[string]interface{}{
					"key": "value",
				},
				"data": "value2",
			},
			keys:       []string{"config.key"},
			filterIn:   false,
			wantResult: map[string]interface{}{"config": map[string]interface{}{}, "data": "value2"},
		},
		{
			name: "FilterInSingleKey",
			ds: map[string]interface{}{
				"config": "value1",
				"data":   "value2",
			},
			keys:       []string{"config"},
			filterIn:   true,
			wantResult: map[string]interface{}{"config": "value1"},
		},
		{
			name: "FilterInNestedKey",
			ds: map[string]interface{}{
				"config": map[string]interface{}{
					"key": "value",
				},
				"data": "value2",
			},
			keys:     []string{"config.key"},
			filterIn: true,
			wantResult: map[string]interface{}{
				"config": map[string]interface{}{
					"key": "value",
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotResult := filterDataStructure(tt.ds, tt.keys, tt.filterIn)
			if !reflect.DeepEqual(gotResult, tt.wantResult) {
				t.Errorf("filterDataStructure() = %v, want %v", gotResult, tt.wantResult)
			}
		})
	}
}

func TestLoadConfigFile(t *testing.T) {
	tests := []struct {
		name        string
		fileContent string
		fileExt     string // Use this to create files with the correct extension
		wantData    interface{}
		wantErr     bool
	}{
		{
			name:        "Load YAML config from string",
			fileContent: `key: value`,
			fileExt:     ".yaml",
			wantData:    map[string]interface{}{"key": "value"},
			wantErr:     false,
		},
		{
			name:        "Load JSON config from string",
			fileContent: `{"key": "value"}`,
			fileExt:     ".json",
			wantData:    map[string]interface{}{"key": "value"},
			wantErr:     false,
		},
		{
			name:        "Load TOML config from string",
			fileContent: `key = "value"`,
			fileExt:     ".toml",
			wantData:    map[string]interface{}{"key": "value"},
			wantErr:     false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Create a temp file
			tmpFile, err := os.CreateTemp("", "config-*"+tt.fileExt)
			if err != nil {
				t.Fatalf("Failed to create temp file: %v", err)
			}
			defer os.Remove(tmpFile.Name()) // Clean up

			// Write the literal content to the temp file
			if _, err := tmpFile.Write([]byte(tt.fileContent)); err != nil {
				t.Fatalf("Failed to write to temp file: %v", err)
			}
			if err := tmpFile.Close(); err != nil {
				t.Fatalf("Failed to close temp file: %v", err)
			}

			// Now test loadConfigFile with the temp file path
			gotData, err := loadConfigFile(tmpFile.Name())
			if (err != nil) != tt.wantErr {
				t.Errorf("loadConfigFile() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(gotData, tt.wantData) && !tt.wantErr {
				t.Errorf("loadConfigFile() got = %v, want %v", gotData, tt.wantData)
			}
		})
	}
}
