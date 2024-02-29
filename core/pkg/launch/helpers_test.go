package launch

import (
	"os"
	"reflect"
	"testing"
)

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
func TestEndpointToComponents(t *testing.T) {
	tests := []struct {
		name       string
		endpoint   string
		wantResult []string
	}{
		{
			name:       "SingleComponent",
			endpoint:   "key",
			wantResult: []string{"key"},
		},
		{
			name:       "MultipleComponents",
			endpoint:   "key1.key2.key3",
			wantResult: []string{"key1", "key2", "key3"},
		},
		{
			name:       "EscapedSeparator",
			endpoint:   "key\\.with\\.dots",
			wantResult: []string{"key.with.dots"},
		},
		{
			name:       "MixedEscapedAndUnescapedSeparators",
			endpoint:   "key1\\.with\\.dots.key2",
			wantResult: []string{"key1.with.dots", "key2"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotResult := splitEndpoint(tt.endpoint)
			if !reflect.DeepEqual(gotResult, tt.wantResult) {
				t.Errorf("endpointToComponents() = %v, want %v", gotResult, tt.wantResult)
			}
		})
	}
}
func TestFilterOutEndpoints(t *testing.T) {
	tests := []struct {
		name       string
		data       interface{}
		endpoints  []string
		wantResult interface{}
		wantErr    bool
	}{
		{
			name:       "Filter out single endpoint",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": "value"}},
			endpoints:  []string{"key1.key2"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{}},
			wantErr:    false,
		},
		{
			name:       "Filter out multiple endpoints",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": "value", "key3": "value"}},
			endpoints:  []string{"key1.key2", "key1.key3"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{}},
			wantErr:    false,
		},
		{
			name:       "Filter out nested endpoint",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": map[string]interface{}{"key3": "value"}}},
			endpoints:  []string{"key1.key2.key3"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{"key2": map[string]interface{}{}}},
			wantErr:    false,
		},
		{
			name:      "Filter out endpoint with list index",
			data:      map[string]interface{}{"key1": []interface{}{"value1", "value2", "value3"}},
			endpoints: []string{"key1.1"},
			wantResult: map[string]interface{}{
				"key1": []interface{}{"value1", "value3"},
			},
			wantErr: false,
		},
		{
			name:       "Filter out dict within list",
			data:       map[string]interface{}{"key1": []interface{}{map[string]interface{}{"key2": "value"}}},
			endpoints:  []string{"key1.0.key2"},
			wantResult: map[string]interface{}{"key1": []interface{}{map[string]interface{}{}}},
			wantErr:    false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotResult, err := filterOutEndpoints(tt.data, tt.endpoints)
			if (err != nil) != tt.wantErr {
				t.Errorf("filterOutEndpoints() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(gotResult, tt.wantResult) && !tt.wantErr {
				t.Errorf("filterOutEndpoints() got = %v, want %v", gotResult, tt.wantResult)
			}
		})
	}
}
func TestFilterInEndpoints(t *testing.T) {
	tests := []struct {
		name       string
		data       interface{}
		endpoints  []string
		wantResult interface{}
		wantErr    bool
	}{
		{
			name:       "Filter in single endpoint",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": "value"}},
			endpoints:  []string{"key1.key2"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{"key2": "value"}},
			wantErr:    false,
		},
		{
			name:       "Filter in multiple endpoints",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": "value", "key3": "value"}},
			endpoints:  []string{"key1.key2", "key1.key3"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{"key2": "value", "key3": "value"}},
			wantErr:    false,
		},
		{
			name:       "Filter in nested endpoint",
			data:       map[string]interface{}{"key1": map[string]interface{}{"key2": map[string]interface{}{"key3": "value"}}},
			endpoints:  []string{"key1.key2.key3"},
			wantResult: map[string]interface{}{"key1": map[string]interface{}{"key2": map[string]interface{}{"key3": "value"}}},
			wantErr:    false,
		},
		{
			name:      "Filter in endpoint with list index",
			data:      map[string]interface{}{"key1": []interface{}{"value1", "value2", "value3"}},
			endpoints: []string{"key1.1"},
			wantResult: map[string]interface{}{
				"key1": []interface{}{"value2"},
			},
			wantErr: false,
		},
		{
			name:       "Filter in dict within list",
			data:       map[string]interface{}{"key1": []interface{}{map[string]interface{}{"key2": "value"}}},
			endpoints:  []string{"key1.0.key2"},
			wantResult: map[string]interface{}{"key1": []interface{}{map[string]interface{}{"key2": "value"}}},
			wantErr:    false,
		},
		{
			name: "Multiple endpoints with complex nesting",
			data: map[string]interface{}{
				"key1": map[string]interface{}{
					"key2": map[string]interface{}{
						"key3": "value",
						"key4": "value",
					},
					"key5": []interface{}{
						map[string]interface{}{
							"key6": "value",
							"key7": "value",
						},
						map[string]interface{}{
							"key8": "value",
							"key9": "value",
						},
					},
				},
			},
			endpoints: []string{
				"key1.key2.key3",
				"key1.key2.key4",
				"key1.key5.0.key6",
				"key1.key5.1.key8",
			},
			wantResult: map[string]interface{}{
				"key1": map[string]interface{}{
					"key2": map[string]interface{}{
						"key3": "value",
						"key4": "value",
					},
					"key5": []interface{}{
						map[string]interface{}{
							"key6": "value",
						},
						map[string]interface{}{
							"key8": "value",
						},
					},
				},
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotResult, err := filterInEndpoints(tt.data, tt.endpoints)
			if (err != nil) != tt.wantErr {
				t.Errorf("filterInEndpoints() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(gotResult, tt.wantResult) && !tt.wantErr {
				t.Errorf("filterInEndpoints() got = %v, want %v", gotResult, tt.wantResult)
			}
		})
	}
}
