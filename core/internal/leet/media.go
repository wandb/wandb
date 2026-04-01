package leet

import (
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
)

// MediaPoint is a single media sample logged at a particular X-axis value.
//
// For wandb.Image v1, X is the history step. The type is intentionally generic
// so the pane can later be extended to other X axes without changing the data
// model.
type MediaPoint struct {
	X            float64
	FilePath     string
	RelativePath string
	Caption      string
	Format       string
	Width        int
	Height       int
	SHA256       string
}

// MediaStore holds all image series for one run.
//
// Series are keyed by the logged history key (for example
// "media/generated_sample"). Samples within a series are ordered by X.
type MediaStore struct {
	mu sync.RWMutex

	series  map[string][]MediaPoint
	keys    []string
	xValues []float64
}

func NewMediaStore() *MediaStore {
	return &MediaStore{series: make(map[string][]MediaPoint)}
}

// ProcessHistory ingests media payloads from a history message.
//
// Returns true when the store changed.
func (s *MediaStore) ProcessHistory(msg HistoryMsg) bool {
	if len(msg.Media) == 0 {
		return false
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	changed := false
	for key, points := range msg.Media {
		if key == "" || len(points) == 0 {
			continue
		}

		if _, ok := s.series[key]; !ok {
			s.keys = append(s.keys, key)
			sort.Strings(s.keys)
			changed = true
		}

		series := s.series[key]
		for _, point := range points {
			var pointChanged bool
			series, pointChanged = upsertMediaPoint(series, point)
			if pointChanged {
				s.appendXValueLocked(point.X)
				changed = true
			}
		}
		s.series[key] = series
	}

	return changed
}

func upsertMediaPoint(series []MediaPoint, point MediaPoint) ([]MediaPoint, bool) {
	// First index whose X is strictly greater than point.X.
	idx := sort.Search(len(series), func(i int) bool {
		return series[i].X > point.X
	})

	// Last writer wins at a given X.
	if idx > 0 && series[idx-1].X == point.X {
		if series[idx-1] == point {
			return series, false
		}
		series[idx-1] = point
		return series, true
	}

	series = append(series, MediaPoint{})
	copy(series[idx+1:], series[idx:])
	series[idx] = point
	return series, true
}

func (s *MediaStore) appendXValueLocked(x float64) {
	if len(s.xValues) == 0 || x > s.xValues[len(s.xValues)-1] {
		s.xValues = append(s.xValues, x)
		return
	}

	idx, found := slices.BinarySearch(s.xValues, x)
	if found {
		return
	}

	s.xValues = append(s.xValues, 0)
	copy(s.xValues[idx+1:], s.xValues[idx:])
	s.xValues[idx] = x
}

// SeriesKeys returns the sorted set of media series keys.
func (s *MediaStore) SeriesKeys() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return slices.Clone(s.keys)
}

// XValues returns the sorted union of X-axis values across all media series.
func (s *MediaStore) XValues() []float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return slices.Clone(s.xValues)
}

// SeriesXValues returns the sorted X-axis values for a single series.
func (s *MediaStore) SeriesXValues(key string) []float64 {
	s.mu.RLock()
	defer s.mu.RUnlock()

	series := s.series[key]
	if len(series) == 0 {
		return nil
	}
	xs := make([]float64, len(series))
	for i, p := range series {
		xs[i] = p.X
	}
	return xs
}

// ResolveAt returns the most recent media sample for key whose X <= x.
func (s *MediaStore) ResolveAt(key string, x float64) (MediaPoint, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	series := s.series[key]
	if len(series) == 0 {
		return MediaPoint{}, false
	}

	idx := sort.Search(len(series), func(i int) bool {
		return series[i].X > x
	})
	if idx == 0 {
		return MediaPoint{}, false
	}
	return series[idx-1], true
}

// Empty reports whether the store contains any media series.
func (s *MediaStore) Empty() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.keys) == 0
}

// resolveMediaPath resolves a media file path from a history record to the file
// on disk for the given run.
func resolveMediaPath(runPath, relativePath string) string {
	if relativePath == "" {
		return ""
	}
	if filepath.IsAbs(relativePath) {
		return filepath.Clean(relativePath)
	}

	clean := filepath.Clean(string(filepath.Separator) + relativePath)
	clean = strings.TrimPrefix(clean, string(filepath.Separator))

	return filepath.Join(filepath.Dir(runPath), "files", clean)
}
