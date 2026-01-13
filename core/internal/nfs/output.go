package nfs

import (
	"fmt"
	"io"
	"sort"
)

// PrintCollections prints collections in tree format.
func PrintCollections(w io.Writer, collections []CollectionInfo) {
	if len(collections) == 0 {
		fmt.Fprintln(w, "(no artifact collections found)")
		return
	}

	// Sort collections by name for consistent output
	sort.Slice(collections, func(i, j int) bool {
		return collections[i].Name < collections[j].Name
	})

	for _, coll := range collections {
		fmt.Fprintf(w, "%s/\n", coll.Name)

		// Sort versions by index
		sort.Slice(coll.Versions, func(i, j int) bool {
			return coll.Versions[i].Index < coll.Versions[j].Index
		})

		for _, v := range coll.Versions {
			fmt.Fprintf(w, "   v%d\n", v.Index)
		}
	}
}
