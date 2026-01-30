package leet

import (
	"math"
	"strconv"
	"strings"
)

// formatSigFigs formats the float with 'prec' significant digits.
//
// It uses 'g' format, which removes trailing zeros and handles
// switching to scientific notation for very small/large numbers automatically.
func formatSigFigs(v float64, prec int) string {
	return strconv.FormatFloat(v, 'g', prec, 64)
}

// UnitFormatter formats a scalar for axis labels and exposes the base unit to show in titles.
type UnitFormatter interface {
	// Format formats value is in this unit's native measurement.
	Format(value float64) string

	// Name returns base unit symbol without prefixes, e.g. "B", "Hz", "W", "%", "°C", or "".
	Name() string
}

// Dimensionless numbers (epoch charts, counters, etc.).
var UnitScalar UnitFormatter = unitNone{}

// Percentages (0..100).
var UnitPercent UnitFormatter = unitPercent{}

// Temperature in Celsius.
var UnitCelsius UnitFormatter = unitCelsius{}

// Power in Watts.
var UnitWatt UnitFormatter = unitWatt{}

// Frequency measured in MHz, titled in Hz.
var UnitMHz UnitFormatter = unitMHz{}

// Bytes in base units (value already in bytes).
var UnitBytes UnitFormatter = unitBytes{factorToBytes: 1}

// Bytes where value is provided in MiB/GiB but title wants base "B".
var UnitMiB UnitFormatter = unitBytes{factorToBytes: 1024 * 1024}
var UnitGiB UnitFormatter = unitBytes{factorToBytes: 1024 * 1024 * 1024}

// Byte rates: values provided in B/s, MiB/s, GiB/s; title wants "B/s".
var UnitBps UnitFormatter = unitBytesPerSecond{factorToBps: 1}
var UnitMiBps UnitFormatter = unitBytesPerSecond{factorToBps: 1024 * 1024}
var UnitGiBps UnitFormatter = unitBytesPerSecond{factorToBps: 1024 * 1024 * 1024}

type unitNone struct{}

func (unitNone) Name() string { return "" }
func (unitNone) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	return formatSigFigs(v, 3)
}

type unitPercent struct{}

func (unitPercent) Name() string { return "%" }
func (unitPercent) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	return formatSigFigs(v, 3) + "%"
}

type unitCelsius struct{}

func (unitCelsius) Name() string { return "°C" }
func (unitCelsius) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	return formatSigFigs(v, 3) + "°C"
}

type unitWatt struct{}

func (unitWatt) Name() string { return "W" }
func (unitWatt) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	absV := math.Abs(v)
	switch {
	case absV >= 1000:
		return formatSigFigs(v/1000, 3) + "kW"
	default:
		return formatSigFigs(v, 3) + "W"
	}
}

type unitMHz struct{}

func (unitMHz) Name() string { return "Hz" }
func (unitMHz) Format(v float64) string {
	// v is in MHz.
	if v == 0 {
		return "0"
	}
	absV := math.Abs(v)
	switch {
	case absV >= 1000:
		return formatSigFigs(v/1000, 3) + "GHz"
	default:
		return formatSigFigs(v, 3) + "MHz"
	}
}

type unitBytes struct{ factorToBytes float64 }

func (unitBytes) Name() string { return "B" }
func (u unitBytes) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	return formatBytesBinary(v * u.factorToBytes)
}

type unitBytesPerSecond struct{ factorToBps float64 }

func (unitBytesPerSecond) Name() string { return "B/s" }
func (u unitBytesPerSecond) Format(v float64) string {
	if v == 0 {
		return "0"
	}
	return formatRateDecimal(v * u.factorToBps)
}

// Binary prefixes: B, KiB, MiB, GiB, TiB.
func formatBytesBinary(bytes float64) string {
	units := []string{"B", "KiB", "MiB", "GiB", "TiB"}
	unitIndex := 0
	value := bytes
	for unitIndex < len(units)-1 && math.Abs(value) >= 1024 {
		value /= 1024
		unitIndex++
	}
	return formatSigFigs(value, 3) + units[unitIndex]
}

// Decimal prefixes for rates: B/s, KB/s, MB/s, GB/s.
func formatRateDecimal(bps float64) string {
	absBps := math.Abs(bps)
	switch {
	case absBps >= 1e9:
		return formatSigFigs(bps/1e9, 3) + "GB/s"
	case absBps >= 1e6:
		return formatSigFigs(bps/1e6, 3) + "MB/s"
	case absBps >= 1e3:
		return formatSigFigs(bps/1e3, 3) + "KB/s"
	default:
		return formatSigFigs(bps, 3) + "B/s"
	}
}

var scales = []struct {
	factor float64
	suffix string
}{
	{1e3, "k"},
	{1e6, "M"},
	{1e9, "B"},
	{1e12, "T"},
	{1e15, "P"},
	{1e18, "E"},
}

func FormatXAxisTick(v float64, maxWidth int) string {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return ""
	}
	if v == 0 {
		return "0"
	}

	sign := ""
	if v < 0 {
		sign = "-"
		v = -v
	}

	// Only display integers for values < 1000.
	if v < 1000 {
		return sign + strconv.FormatInt(int64(math.Round(v)), 10)
	}

	// Pick a scale so scaled is roughly in [1, 1000).
	idx := 0
	for idx+1 < len(scales) && v >= scales[idx+1].factor {
		idx++
	}

scale:
	for {
		s := scales[idx]
		scaled := v / s.factor

		for decimals := 2; decimals >= 0; decimals-- {
			num := trimTrailingZeros(strconv.FormatFloat(scaled, 'f', decimals, 64))

			// Rounding crossed into next tier (e.g., 999.6k -> 1000k); bump suffix.
			if num == "1000" && idx+1 < len(scales) {
				idx++
				continue scale
			}

			out := sign + num + s.suffix
			if maxWidth <= 0 || len(out) <= maxWidth {
				return out
			}
		}

		// Nothing fit; return minimum precision anyway.
		return sign + trimTrailingZeros(strconv.FormatFloat(scaled, 'f', 0, 64)) + s.suffix
	}
}

func trimTrailingZeros(s string) string {
	if dot := strings.IndexByte(s, '.'); dot != -1 {
		s = strings.TrimRight(s, "0")
		s = strings.TrimSuffix(s, ".")
	}
	return s
}
