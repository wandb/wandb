package launch

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestFilterDoesntMutateConfig(t *testing.T) {
	config := NewConfigFrom(ConfigDict{
		"number": 9,
		"nested": ConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	include_paths := []ConfigPath{
		{"nested"},
	}
	exclude_paths := []ConfigPath{
		{"nested", "text"},
	}

	config.filterTree(include_paths, exclude_paths)

	assert.Equal(t,
		NewConfigFrom(ConfigDict{
			"number": 9,
			"nested": ConfigDict{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		}),
		config,
	)
}

func TestFilterTree_Include(t *testing.T) {
	config := NewConfigFrom(ConfigDict{
		"number": 9,
		"nested": ConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	paths := []ConfigPath{
		{"number"},
		{"nested", "list"},
	}

	include_tree := config.filterTree(paths, nil)

	assert.Equal(t,
		ConfigDict{
			"number": 9,
			"nested": ConfigDict{
				"list": []string{"a", "b", "c"},
			},
		},
		include_tree,
	)
}

func TestFilterTree_Exclude(t *testing.T) {
	config := NewConfigFrom(ConfigDict{
		"number": 9,
		"nested": ConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	paths := []ConfigPath{
		{"number"},
		{"nested", "list"},
	}

	exclude_tree := config.filterTree(nil, paths)

	assert.Equal(t,
		ConfigDict{
			"nested": ConfigDict{
				"text": "xyz",
			},
		},
		exclude_tree,
	)
}

func TestFilterTree_IncludeAndExclude(t *testing.T) {
	config := NewConfigFrom(ConfigDict{
		"number": 9,
		"nested": ConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	include_paths := []ConfigPath{
		{"nested"},
	}
	exclude_paths := []ConfigPath{
		{"nested", "text"},
	}

	include_exclude_tree := config.filterTree(include_paths, exclude_paths)

	assert.Equal(t,
		ConfigDict{
			"nested": ConfigDict{
				"list": []string{"a", "b", "c"},
			},
		},
		include_exclude_tree,
	)
}

func TestFilterTree_DeeplyNested(t *testing.T) {
	config := NewConfigFrom(ConfigDict{
		"key1": "value1",
		"key2": ConfigDict{
			"key3": "value3",
			"key4": ConfigDict{
				"key5": "value5",
				"key6": ConfigDict{
					"key7": "value7",
					"key8": "value8",
				},
			},
		},
	})
	include_paths := []ConfigPath{{"key2"}}
	exclude_paths := []ConfigPath{
		{"key2", "key4", "key6", "key8"},
		{"key2", "key3"},
	}

	include_exclude_tree := config.filterTree(include_paths, exclude_paths)

	assert.Equal(t,
		ConfigDict{
			"key2": ConfigDict{
				"key4": ConfigDict{
					"key5": "value5",
					"key6": ConfigDict{
						"key7": "value7",
					},
				},
			},
		},
		include_exclude_tree,
	)

}
