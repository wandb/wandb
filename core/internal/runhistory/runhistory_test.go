package runhistory_test

import (
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestApplyUpdate(t *testing.T) {

	rh := runhistory.New()
	items := []*service.HistoryItem{
		{
			Key:       "setting1",
			ValueJson: "69",
		},
		{
			NestedKey: []string{"config", "setting2"},
			ValueJson: `{"value": 42}`,
		},
	}

	rh.ApplyChangeRecord(items,
		func(err error) {
			t.Error("onError should not be called", err)
		})

	encoded, err := rh.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"setting1": 69,
			"config": {"setting2": {"value": 42}}
		}`,
		string(encoded))
}

func key(item *service.HistoryItem) []string {
	if len(item.GetNestedKey()) > 0 {
		return item.GetNestedKey()
	}
	return []string{item.GetKey()}
}

// TestApplyUpdateSpecialValues checks behavior with NaN and Inf values.
// These values are supported by our special json package and should not return an error.
func TestApplyUpdateSpecialValues(t *testing.T) {

	rh := runhistory.New()
	expectedItems := []*service.HistoryItem{
		{
			Key:       "nan",
			ValueJson: `NaN`,
		},
		{
			Key:       "inf",
			ValueJson: `Infinity`,
		},
		{
			NestedKey: []string{"special", "ninf"},
			ValueJson: `-Infinity`,
		},
	}
	rh.ApplyChangeRecord(expectedItems,
		func(err error) {
			t.Error("onError should not be called", err)
		})

	actualItems, err := rh.Flatten()
	if err != nil {
		t.Fatal("Flatten failed:", err)
	}

	// Sort slices by joining keys into a single string for comparison
	// (since order is not guaranteed)
	sort.Slice(actualItems, func(i, j int) bool {
		return strings.Join(key(actualItems[i]), ".") <
			strings.Join(key(actualItems[j]), ".")
	})

	sort.Slice(expectedItems, func(i, j int) bool {
		return strings.Join(key(expectedItems[i]), ".") <
			strings.Join(key(expectedItems[j]), ".")
	})

	if !reflect.DeepEqual(actualItems, expectedItems) {
		t.Errorf("Expected %v, got %v", expectedItems, actualItems)
	}
}

func TestSerialize(t *testing.T) {
	rh := runhistory.New()

	rh.ApplyChangeRecord([]*service.HistoryItem{
		{Key: "config", ValueJson: `{"setting1":"value1"}`},
	}, func(err error) {})

	actualJson, err := rh.Serialize()
	if err != nil {
		t.Fatal("Serialize failed:", err)
	}

	expectedJson := "{\"config\":{\"setting1\":\"value1\"}}"

	if string(actualJson) != expectedJson {
		t.Errorf("Expected %v, got %v", expectedJson, string(actualJson))
	}

}
