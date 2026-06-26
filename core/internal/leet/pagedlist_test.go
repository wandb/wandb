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

func TestPagedList_End_JumpsToLastItem(t *testing.T) {
	// 5 items, 2 per page -> 3 pages: [a b][c d][e]; End -> last page, last line.
	list := leet.PagedList{
		FilteredItems: []leet.KeyValuePair{
			{Key: "a"}, {Key: "b"}, {Key: "c"}, {Key: "d"}, {Key: "e"},
		},
	}
	list.SetItemsPerPage(2)

	list.End()
	item, ok := list.CurrentItem()
	require.True(t, ok)
	require.Equal(t, "e", item.Key)
	require.Equal(t, 2, list.CurrentPage())
	require.Equal(t, 0, list.CurrentLine())

	// Full last page: 4 items, 2 per page -> End lands on (page 1, line 1).
	full := leet.PagedList{
		FilteredItems: []leet.KeyValuePair{{Key: "a"}, {Key: "b"}, {Key: "c"}, {Key: "d"}},
	}
	full.SetItemsPerPage(2)
	full.End()
	require.Equal(t, 1, full.CurrentPage())
	require.Equal(t, 1, full.CurrentLine())
}
