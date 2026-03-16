package leet_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestPagedList_EmptyNavigation_IsStable(t *testing.T) {
	var list leet.PagedList

	list.Up()
	list.Down()
	list.PageUp()
	list.PageDown()
	list.Home()

	item, ok := list.CurrentItem()
	require.False(t, ok)
	require.Equal(t, leet.KeyValuePair{}, item)
	require.Equal(t, 0, list.CurrentPage())
	require.Equal(t, 0, list.CurrentLine())
}

func TestPagedList_SetItemsPerPage_ZeroDisablesNavigation(t *testing.T) {
	list := leet.PagedList{
		FilteredItems: []leet.KeyValuePair{{Key: "a"}, {Key: "b"}},
	}

	list.SetItemsPerPage(0)
	require.Equal(t, 0, list.ItemsPerPage())

	list.Down()
	list.PageDown()
	_, ok := list.CurrentItem()
	require.False(t, ok)
	require.Equal(t, 0, list.CurrentPage())
	require.Equal(t, 0, list.CurrentLine())

	list.SetItemsPerPage(1)
	item, ok := list.CurrentItem()
	require.True(t, ok)
	require.Equal(t, "a", item.Key)
}
