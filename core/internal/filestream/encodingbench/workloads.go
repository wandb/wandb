package encodingbench

import (
	"fmt"
	"math"
	"strings"
)

// SyntheticWorkloads returns deterministic workloads representing important
// history and system-metrics shapes. The returned datasets are safe to reuse.
func SyntheticWorkloads() []Dataset {
	return []Dataset{
		makeDenseNumeric("tiny", 1, 8),
		makeDenseNumeric("dense_numeric", 128, 256),
		makeSparseMixed("sparse_mixed", 512, 2048, 32),
		makeWideMixed("wide_mixed", 16, 2048),
		makeNestedJSON("nested_json", 128, 64),
		makeSystemMetrics("system_metrics", 1024, 64),
	}
}

func makeDenseNumeric(name string, rowCount, width int) Dataset {
	rows := make([]Row, rowCount)
	for rowIndex := range rows {
		cells := make([]Cell, width)
		for columnIndex := range cells {
			value := float64(rowIndex*width+columnIndex) / 10
			if rowIndex == 0 {
				switch columnIndex {
				case 0:
					value = math.NaN()
				case 1:
					value = math.Inf(1)
				case 2:
					value = math.Inf(-1)
				}
			}
			cells[columnIndex] = Cell{
				Key:   fmt.Sprintf("metric_%04d", columnIndex),
				Value: Value{Kind: KindNumber, Number: value},
			}
		}
		rows[rowIndex] = Row{Cells: cells}
	}
	return Dataset{Name: name, Rows: rows}
}

func makeSparseMixed(name string, rowCount, keySpace, width int) Dataset {
	rows := make([]Row, rowCount)
	for rowIndex := range rows {
		cells := make([]Cell, width)
		for cellIndex := range cells {
			keyIndex := (rowIndex*37 + cellIndex*61) % keySpace
			cells[cellIndex] = Cell{
				Key:   fmt.Sprintf("sparse_%04d", keyIndex),
				Value: mixedValue(rowIndex, cellIndex),
			}
		}
		rows[rowIndex] = Row{Cells: cells}
	}
	return Dataset{Name: name, Rows: rows}
}

func makeWideMixed(name string, rowCount, width int) Dataset {
	rows := make([]Row, rowCount)
	for rowIndex := range rows {
		cells := make([]Cell, width)
		for columnIndex := range cells {
			cells[columnIndex] = Cell{
				Key:   fmt.Sprintf("wide_%05d", columnIndex),
				Value: mixedValue(rowIndex, columnIndex),
			}
		}
		rows[rowIndex] = Row{Cells: cells}
	}
	return Dataset{Name: name, Rows: rows}
}

func makeNestedJSON(name string, rowCount, width int) Dataset {
	rows := make([]Row, rowCount)
	for rowIndex := range rows {
		cells := make([]Cell, width)
		for columnIndex := range cells {
			jsonValue := fmt.Sprintf(
				`{"values":[%d,%d,%d],"metadata":{"group":"g%d","active":%t}}`,
				rowIndex,
				columnIndex,
				rowIndex+columnIndex,
				columnIndex%8,
				columnIndex%2 == 0,
			)
			cells[columnIndex] = Cell{
				Key:   fmt.Sprintf("media_%03d", columnIndex),
				Value: Value{Kind: KindJSON, JSON: []byte(jsonValue)},
			}
		}
		rows[rowIndex] = Row{Cells: cells}
	}
	return Dataset{Name: name, Rows: rows}
}

func makeSystemMetrics(name string, rowCount, width int) Dataset {
	rows := make([]Row, rowCount)
	for rowIndex := range rows {
		cells := make([]Cell, width)
		for columnIndex := range cells {
			cells[columnIndex] = Cell{
				Key: fmt.Sprintf("system.device.%02d.metric.%02d", columnIndex/8, columnIndex),
				Value: Value{
					Kind:   KindNumber,
					Number: float64((rowIndex+1)*(columnIndex+3)%10000) / 100,
				},
			}
		}
		rows[rowIndex] = Row{Cells: cells}
	}
	return Dataset{Name: name, Rows: rows}
}

func mixedValue(rowIndex, columnIndex int) Value {
	switch columnIndex % 5 {
	case 0:
		return Value{Kind: KindNull}
	case 1:
		return Value{Kind: KindBool, Bool: (rowIndex+columnIndex)%2 == 0}
	case 2:
		return Value{Kind: KindNumber, Number: float64(rowIndex*31+columnIndex) / 7}
	case 3:
		length := 8 + (rowIndex+columnIndex)%96
		return Value{
			Kind:   KindString,
			String: strings.Repeat(string(rune('a'+columnIndex%26)), length),
		}
	default:
		return Value{
			Kind: KindJSON,
			JSON: []byte(
				fmt.Sprintf(`[%d,%d,{"bucket":%d}]`, rowIndex, columnIndex, columnIndex%16),
			),
		}
	}
}
