package leet

import (
	"math"
	"math/rand"
	"testing"

	"github.com/NimbleMarkets/ntcharts/v2/canvas"
	"github.com/NimbleMarkets/ntcharts/v2/canvas/graph"
)

// rasterizeSeriesReference is the pre-optimization drawSeries algorithm:
// one Bresenham segment per adjacent sample pair. rasterizeSeries must set
// exactly the same braille dots.
func rasterizeSeriesReference(
	c *EpochLineChart,
	bGrid *graph.BrailleGrid,
	s *Series,
	lb, ub int,
) {
	xScale := float64(c.GraphWidth()) / (c.ViewMaxX() - c.ViewMinX())
	yScale := float64(c.GraphHeight()) / (c.ViewMaxY() - c.ViewMinY())

	segments := make([][]canvas.Float64Point, 0, 1)
	current := make([]canvas.Float64Point, 0, ub-lb)
	flush := func() {
		if len(current) == 0 {
			return
		}
		segments = append(segments, current)
		current = make([]canvas.Float64Point, 0, ub-lb)
	}

	for i := lb; i < ub; i++ {
		yValue, ok := c.scaleYValue(s.Y[i])
		if !ok {
			flush()
			continue
		}
		x := (s.X[i] - c.ViewMinX()) * xScale
		y := (yValue - c.ViewMinY()) * yScale
		if x < 0 || x > float64(c.GraphWidth()) || y < 0 || y > float64(c.GraphHeight()) {
			flush()
			continue
		}
		current = append(current, canvas.Float64Point{X: x, Y: y})
	}
	flush()

	for _, points := range segments {
		if len(points) == 1 {
			bGrid.Set(bGrid.GridPoint(points[0]))
			continue
		}
		for i := range len(points) - 1 {
			drawLine(bGrid, bGrid.GridPoint(points[i]), bGrid.GridPoint(points[i+1]))
		}
	}
}

func newBrailleGridFor(c *EpochLineChart) *graph.BrailleGrid {
	return graph.NewBrailleGrid(
		c.GraphWidth(), c.GraphHeight(),
		0, float64(c.GraphWidth()),
		0, float64(c.GraphHeight()),
	)
}

func TestRasterizeSeriesMatchesReference(t *testing.T) {
	rng := rand.New(rand.NewSource(42))

	shapes := map[string]func(i int) (x, y float64){
		"noisy_walk": func(i int) (float64, float64) {
			return float64(i), math.Sin(float64(i)/8) + rng.Float64()*3
		},
		"smooth": func(i int) (float64, float64) {
			return float64(i), math.Sin(float64(i) / 40)
		},
		"with_gaps": func(i int) (float64, float64) {
			y := float64(i % 13)
			if i%37 == 0 {
				y = math.NaN()
			}
			return float64(i), y
		},
		"steep_spikes": func(i int) (float64, float64) {
			y := 0.0
			if i%50 == 0 {
				y = 1000
			}
			return float64(i), y
		},
		"sparse_x": func(i int) (float64, float64) {
			return float64(i * i), float64(i % 7)
		},
	}

	for name, gen := range shapes {
		for _, n := range []int{1, 2, 5, 300, 5000} {
			c := NewEpochLineChart("test")
			for i := range n {
				x, y := gen(i)
				c.AddData("s", MetricData{X: []float64{x}, Y: []float64{y}})
			}
			c.Resize(48, 12)

			s := c.data["s"]
			for _, zoomed := range []bool{false, true} {
				if zoomed && n >= 4 {
					// Zoom into the middle half of the data to exercise
					// partially visible windows.
					c.SetViewXRange(s.X[n/4], s.X[3*n/4])
				}

				lb := 0
				ub := len(s.X)

				got := newBrailleGridFor(c)
				c.rasterizeSeries(got, s, lb, ub)

				want := newBrailleGridFor(c)
				rasterizeSeriesReference(c, want, s, lb, ub)

				gotPat := got.BraillePatterns()
				wantPat := want.BraillePatterns()
				for row := range wantPat {
					for col := range wantPat[row] {
						if gotPat[row][col] != wantPat[row][col] {
							t.Fatalf("%s n=%d zoomed=%v: dot mismatch at (%d,%d): got %q want %q",
								name, n, zoomed, col, row,
								gotPat[row][col], wantPat[row][col])
						}
					}
				}
			}
		}
	}
}
