package main

// -chartdump mode: the Phase 3 exit differential for leet-charts.
//
// Constructs leet charts (EpochLineChart, FrenchFriesChart) through exported
// APIs only, applies a scripted op sequence per case, renders View(), strips
// ANSI, and prints the rune grid with a per-case header. The Rust side
// (leet/crates/leet-charts/tests/canvas_differential.rs) regenerates the SAME
// cases through the Rust ports and compares rune grids char-for-char against
// the committed golden produced by this tool.
//
// Determinism: no RNG (all values are closed-form with explicit float64
// temporaries so Go cannot fuse a*b+c into FMA), no time.Now (fixed base
// timestamps), and time.Local is pinned to UTC (the Rust port renders time
// labels in UTC — recorded DIVERGENCE(TZ) in french_fries_chart.rs /
// timeseries_line_chart.rs).

import (
	"fmt"
	"io"
	"math"
	"regexp"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/leet"
)

// chartDumpViewports lists the outer chart sizes each case renders at.
var chartDumpViewports = []struct{ W, H int }{
	{36, 10},
	{60, 16},
	{100, 24},
}

type chartDumpCase struct {
	name string
	// render builds the chart at the given outer size, applies the case's
	// op sequence, and returns View() (ANSI allowed; stripped by the runner).
	render func(w, h int) string
}

// chartDumpCases is the deterministic case table. Mirrored 1:1 (names and
// construction) in leet/crates/leet-charts/tests/canvas_differential.rs.
var chartDumpCases = []chartDumpCase{
	{name: "linear-50", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", linearData(50))
		return renderEpoch(c)
	}},
	{name: "noisy-sine-200", render: func(w, h int) string {
		c := newEpochChart("accuracy", w, h)
		c.AddData("accuracy", noisySineData(200))
		return renderEpoch(c)
	}},
	{name: "nan-poisoned", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", nanPoisonedData(50))
		return renderEpoch(c)
	}},
	{name: "single-point", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", leet.MetricData{X: []float64{5}, Y: []float64{3.7}})
		return renderEpoch(c)
	}},
	{name: "flat", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", flatData(30, 42.0))
		return renderEpoch(c)
	}},
	{name: "overlay-two-series", render: func(w, h int) string {
		c := newEpochChart("metrics", w, h)
		c.AddData("train", overlayTrainData(60))
		c.AddData("val", overlayValData(60))
		return renderEpoch(c)
	}},
	{name: "overlay-promoted", render: func(w, h int) string {
		c := newEpochChart("metrics", w, h)
		c.AddData("train", overlayTrainData(60))
		c.AddData("val", overlayValData(60))
		c.PromoteSeriesToTop("train")
		return renderEpoch(c)
	}},
	{name: "zoom-in-x2", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", linearData(50))
		gw := c.GraphWidth()
		c.HandleZoom("in", gw/2)
		c.HandleZoom("in", gw/2)
		return renderEpoch(c)
	}},
	{name: "zoom-then-pan", render: func(w, h int) string {
		c := newEpochChart("loss", w, h)
		c.AddData("loss", linearData(50))
		gw := c.GraphWidth()
		c.HandleZoom("in", gw/2)
		c.HandleZoom("in", gw/2)
		// Pan left by a quarter of the zoomed view span via the exported
		// linechart API (explicit temporaries; see file header).
		vmin := c.ViewMinX()
		vmax := c.ViewMaxX()
		span := vmax - vmin
		shift := span * 0.25
		newMin := vmin - shift
		newMax := vmax - shift
		c.SetViewXRange(newMin, newMax)
		return renderEpoch(c)
	}},
	{name: "logy-positive", render: func(w, h int) string {
		c := newEpochChart("lr", w, h)
		c.AddData("lr", logPositiveData(40))
		c.SetYScale(leet.AxisScaleLog)
		return renderEpoch(c)
	}},
	{name: "logy-rejected-mixed", render: func(w, h int) string {
		c := newEpochChart("delta", w, h)
		c.AddData("delta", logRejectedData(20))
		// No strictly positive sample: SetYScale must reject and the chart
		// must render linear.
		c.SetYScale(leet.AxisScaleLog)
		return renderEpoch(c)
	}},
	{name: "french-fries-3x40", render: func(w, h int) string {
		c := newFrenchFriesChart(w, h)
		const base = int64(1_700_000_000)
		for i := 0; i < 40; i++ {
			ts := base + int64(i)*30
			for g := 0; g < 3; g++ {
				c.AddDataPoint(fmt.Sprintf("GPU %d", g), ts, frenchFriesValue(i, g))
			}
		}
		// Widen the bucketing window to the full sample range (AddDataPoint
		// only seeds the default window from the FIRST sample; at runtime the
		// grid drives SetViewWindow).
		c.SetViewWindow(float64(base), float64(base+39*30))
		return c.View()
	}},
	{name: "french-fries-single", render: func(w, h int) string {
		c := newFrenchFriesChart(w, h)
		const base = int64(1_700_000_000)
		for i := 0; i < 25; i++ {
			ts := base + int64(i)*60
			c.AddDataPoint("", ts, frenchFriesSingleValue(i))
		}
		c.SetViewWindow(float64(base), float64(base+24*60))
		return c.View()
	}},
}

// --- chart constructors ------------------------------------------------------

func newEpochChart(title string, w, h int) *leet.EpochLineChart {
	c := leet.NewEpochLineChart(title)
	c.Resize(w, h)
	return c
}

func renderEpoch(c *leet.EpochLineChart) string {
	c.Draw()
	return c.View()
}

func newFrenchFriesChart(w, h int) *leet.FrenchFriesChart {
	def := &leet.MetricDef{
		Name:       "GPU Utilization",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		Percentage: true,
	}
	return leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  w,
		Height: h,
		Def:    def,
		Now:    time.Unix(1_700_000_000, 0),
	})
}

// --- closed-form data (explicit temporaries; no RNG, no transcendentals) ----

// parabolaSine is a deterministic sine-like wave over phase p in [0, 1):
// two parabolic half-waves peaking at ±1. Basic IEEE ops only, so Go and
// Rust produce bit-identical values.
func parabolaSine(p float64) float64 {
	if p < 0.5 {
		a := p * (0.5 - p)
		return 16.0 * a
	}
	a := (p - 0.5) * (1.0 - p)
	return -16.0 * a
}

func linearData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		x := float64(i)
		t := 0.35 * x
		y := t + 2.0
		d.X[i] = x
		d.Y[i] = y
	}
	return d
}

func noisySineData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		x := float64(i)
		p := float64(i%40) / 40.0
		s := parabolaSine(p)
		q := float64((i*7)%23) / 23.0
		wob := parabolaSine(q)
		t1 := s * 10.0
		t2 := wob * 1.5
		amp := 1.0 + float64(i)/400.0
		base := t1 + t2
		scaled := base * amp
		y := scaled + 12.0
		d.X[i] = x
		d.Y[i] = y
	}
	return d
}

func nanPoisonedData(n int) leet.MetricData {
	d := linearData(n)
	for i := 0; i < n; i++ {
		switch {
		case i%7 == 3:
			d.Y[i] = math.NaN()
		case i == 20:
			d.Y[i] = math.Inf(1)
		case i == 35:
			d.Y[i] = math.Inf(-1)
		}
	}
	return d
}

func flatData(n int, v float64) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		d.X[i] = float64(i)
		d.Y[i] = v
	}
	return d
}

func overlayTrainData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		x := float64(i)
		t := 0.5 * x
		y := t + 1.0
		d.X[i] = x
		d.Y[i] = y
	}
	return d
}

func overlayValData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		x := float64(i)
		t := 0.4 * x
		y := 30.0 - t
		d.X[i] = x
		d.Y[i] = y
	}
	return d
}

func logPositiveData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		d.X[i] = float64(i)
		d.Y[i] = 1000.0 / float64(i+1)
	}
	return d
}

func logRejectedData(n int) leet.MetricData {
	d := leet.MetricData{X: make([]float64, n), Y: make([]float64, n)}
	for i := 0; i < n; i++ {
		d.X[i] = float64(i)
		switch i % 3 {
		case 0:
			d.Y[i] = -5.0
		case 1:
			d.Y[i] = 0.0
		default:
			d.Y[i] = math.NaN()
		}
	}
	return d
}

func frenchFriesValue(i, g int) float64 {
	p := float64((i+g*13)%40) / 40.0
	s := parabolaSine(p)
	t := s * 45.0
	return 50.0 + t
}

func frenchFriesSingleValue(i int) float64 {
	p := float64(i%25) / 25.0
	s := parabolaSine(p)
	t := s * 25.0
	return 30.0 + t
}

// --- runner ------------------------------------------------------------------

var ansiRe = regexp.MustCompile(`\x1b\[[0-9;]*m`)

func stripANSIChartDump(s string) string {
	return ansiRe.ReplaceAllString(s, "")
}

// runChartDump prints the golden file to w and returns a process exit code.
func runChartDump(w io.Writer) int {
	// The Rust port renders time labels in UTC (DIVERGENCE(TZ)); pin the
	// oracle to UTC so the grids are environment-independent.
	time.Local = time.UTC

	fmt.Fprintln(w, "# leet chartdump golden: Go leet (oracle) rune grids for the leet-charts differential.")
	fmt.Fprintln(w, "# Regenerate: cd core && go run ./internal/leet/fixturegen -chartdump > ../leet/fixtures/chartdump/golden.txt")
	fmt.Fprintln(w, "# Compared char-for-char by leet/crates/leet-charts/tests/canvas_differential.rs.")
	fmt.Fprintln(w, "# Known divergences: none.")

	for _, tc := range chartDumpCases {
		for _, vp := range chartDumpViewports {
			fmt.Fprintf(w, "=== case %s viewport %dx%d ===\n", tc.name, vp.W, vp.H)
			grid := stripANSIChartDump(tc.render(vp.W, vp.H))
			lines := strings.Split(grid, "\n")
			for _, line := range lines {
				fmt.Fprintln(w, line)
			}
		}
	}
	return 0
}
