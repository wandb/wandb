package wbvalue

import (
	"encoding/json"
	"errors"
)

// Histogram is a histogram logged to a W&B run.
//
// Histograms are logged as a JSON object containing bin edges
// and counts.
type Histogram struct {
	// BinEdges contains the edges of the histogram's bins.
	//
	// Histogram bins must be adjacent. This has one more element
	// than the number of bins---the ith element is the left edge
	// of the ith bin, and the last element is the right edge of
	// the last bin.
	BinEdges []float64

	// BinWeights contains the size of each bin.
	//
	// This can be an integer count or a non-integer number,
	// such as if the histogram is normalized.
	BinWeights []float64
}

// HistoryValueJSON returns the JSON value to log to a run.
func (h Histogram) HistoryValueJSON() (string, error) {
	if len(h.BinEdges) != 1+len(h.BinWeights) {
		return "", errors.New("malformed histogram")
	}

	data, err := json.Marshal(map[string]any{
		"_type":  "histogram",
		"values": h.BinWeights,
		"bins":   h.BinEdges,
	})

	return string(data), err
}
