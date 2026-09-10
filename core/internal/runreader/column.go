package runreader

import (
	"math"
	"slices"
	"sort"
	"strconv"
)

// Chunk is a run of consecutive rows stored by column, the layout pandas,
// polars and numpy build a frame from with no per-value work.
type Chunk struct {
	Rows    int
	Columns []*Column
	byKey   map[string]*Column
}

// Column holds one key's values in exactly one of Ints, when every value is
// an integer, Floats, when every value is a number, or JSON, the values as
// logged. RowIndex lists each value's row and is nil when every row has one.
type Column struct {
	Key      string
	Ints     []int64
	Floats   []float64
	JSON     []string
	RowIndex []uint32
}

func (c *Chunk) column(key string) *Column {
	if col, ok := c.byKey[key]; ok {
		return col
	}
	if c.byKey == nil {
		c.byKey = make(map[string]*Column)
	}
	col := &Column{Key: key}
	c.byKey[key] = col
	c.Columns = append(c.Columns, col)
	return col
}

// add records the value logged as JSON for key in row, which must not be
// before the column's last row.
func (c *Chunk) add(row int, key, valueJSON string) {
	if valueJSON == "" {
		valueJSON = "null"
	}
	col := c.column(key)
	col.place(row)
	switch {
	case col.JSON != nil:
		col.JSON = append(col.JSON, valueJSON)
	case col.Floats != nil:
		if f, ok := parseNumber(valueJSON); ok {
			col.Floats = append(col.Floats, f)
			return
		}
		col.toJSON()
		col.JSON = append(col.JSON, valueJSON)
	default:
		if i, err := strconv.ParseInt(valueJSON, 10, 64); err == nil {
			col.Ints = append(col.Ints, i)
			return
		}
		if f, ok := parseNumber(valueJSON); ok {
			col.toFloats()
			col.Floats = append(col.Floats, f)
			return
		}
		col.toJSON()
		col.JSON = append(col.JSON, valueJSON)
	}
}

func (c *Chunk) addInt(row int, key string, v int64) {
	col := c.column(key)
	col.place(row)
	switch {
	case col.JSON != nil:
		col.JSON = append(col.JSON, strconv.FormatInt(v, 10))
	case col.Floats != nil:
		col.Floats = append(col.Floats, float64(v))
	default:
		col.Ints = append(col.Ints, v)
	}
}

func (c *Chunk) addFloat(row int, key string, f float64) {
	col := c.column(key)
	col.place(row)
	switch {
	case col.JSON != nil:
		col.JSON = append(col.JSON, formatJSONNumber(f))
	case col.Floats != nil:
		col.Floats = append(col.Floats, f)
	default:
		col.toFloats()
		col.Floats = append(col.Floats, f)
	}
}

// finish marks columns that stopped short of the last row as sparse. It must
// be called once all rows have been added.
func (c *Chunk) finish() {
	for _, col := range c.Columns {
		if col.RowIndex == nil && col.len() < c.Rows {
			col.place(c.Rows)
			col.RowIndex = col.RowIndex[:len(col.RowIndex)-1]
		}
	}
}

// dropFront removes the first n rows of a finished chunk.
func (c *Chunk) dropFront(n int) {
	for _, col := range c.Columns {
		k := n
		if col.RowIndex != nil {
			k = sort.Search(len(col.RowIndex), func(i int) bool { return int(col.RowIndex[i]) >= n })
			col.RowIndex = col.RowIndex[k:]
			for i := range col.RowIndex {
				col.RowIndex[i] -= uint32(n)
			}
		}
		col.Ints = col.Ints[min(k, len(col.Ints)):]
		col.Floats = col.Floats[min(k, len(col.Floats)):]
		col.JSON = col.JSON[min(k, len(col.JSON)):]
	}
	c.Rows -= n
	c.Columns = slices.DeleteFunc(c.Columns, func(col *Column) bool { return col.len() == 0 })
}

func (col *Column) len() int {
	return len(col.Ints) + len(col.Floats) + len(col.JSON)
}

// place records that the next value belongs to row, switching the column to
// a sparse representation at the first gap.
func (col *Column) place(row int) {
	n := col.len()
	if col.RowIndex == nil {
		if n == row {
			return
		}
		col.RowIndex = make([]uint32, n, n+1)
		for i := range n {
			col.RowIndex[i] = uint32(i)
		}
	}
	col.RowIndex = append(col.RowIndex, uint32(row))
}

func (col *Column) toFloats() {
	col.Floats = make([]float64, len(col.Ints), len(col.Ints)+1)
	for i, v := range col.Ints {
		col.Floats[i] = float64(v)
	}
	col.Ints = nil
}

func (col *Column) toJSON() {
	col.JSON = make([]string, 0, col.len()+1)
	for _, v := range col.Ints {
		col.JSON = append(col.JSON, strconv.FormatInt(v, 10))
	}
	for _, f := range col.Floats {
		col.JSON = append(col.JSON, formatJSONNumber(f))
	}
	col.Ints, col.Floats = nil, nil
}

// parseNumber parses a JSON number, including the NaN and Infinity tokens
// the SDK writes.
func parseNumber(s string) (float64, bool) {
	f, err := strconv.ParseFloat(s, 64)
	return f, err == nil
}

func formatJSONNumber(f float64) string {
	switch {
	case math.IsNaN(f):
		return "NaN"
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}
