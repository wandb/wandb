package launch_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/pkg/launch"
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

	config.FilterTree(include_paths, exclude_paths)

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

	include_tree := config.FilterTree(paths, nil)

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

	exclude_tree := config.FilterTree(nil, paths)

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

	include_exclude_tree := config.FilterTree(include_paths, exclude_paths)

	assert.Equal(t,
		ConfigDict{
			"nested": ConfigDict{
				"list": []string{"a", "b", "c"},
			},
		},
		include_exclude_tree,
	)
}
