package launch

import (
	"reflect"
	"testing"
)

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
			gotResult := parseNestedPath(tt.endpoint)
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
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := filterOutPaths(tt.data, tt.endpoints)
			if (err != nil) != tt.wantErr {
				t.Errorf("filterOutEndpoints() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(tt.data, tt.wantResult) && !tt.wantErr {
				t.Errorf("filterOutEndpoints() got = %v, want %v", tt.data, tt.wantResult)
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
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotResult, err := filterInPaths(tt.data, tt.endpoints)
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
