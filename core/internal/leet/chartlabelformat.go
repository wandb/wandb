package leet

import (
	"strconv"
	"strings"
)

// FormatYLabel formats Y-axis labels with appropriate units and precision.
//
//gocyclo:ignore
func FormatYLabel(value float64, unit string) string {
	if value == 0 {
		return "0"
	}

	switch unit {
	case "%":
		return formatPercent(value)

	case "°C":
		return formatTemperature(value)

	case "W":
		return formatPower(value)

	case "MHz":
		return formatFrequency(value)

	case "B":
		return formatBytes(value)

	case "MB":
		return formatBytes(value * 1024 * 1024)

	case "GB":
		return formatBytes(value * 1024 * 1024 * 1024)

	default:
		// Handle rates (MB/s, GB/s, etc.)
		if strings.HasSuffix(unit, "/s") {
			baseUnit := strings.TrimSuffix(unit, "/s")
			return formatRate(value, baseUnit)
		}

		// Default: just show the number with appropriate precision
		switch {
		case value >= 1000000:
			return formatFloat(value/1000000, 1) + "M"
		case value >= 1000:
			return formatFloat(value/1000, 1) + "k"
		case value < 0.01:
			return formatFloat(value*1000, 1) + "m"
		case value < 1:
			return formatFloat(value, 2)
		case value < 10:
			return formatFloat(value, 1)
		default:
			return formatFloat(value, 0)
		}
	}
}

func formatPercent(value float64) string {
	switch {
	case value >= 100:
		return formatFloat(value, 0) + "%"
	case value >= 10:
		return formatFloat(value, 1) + "%"
	default:
		return formatFloat(value, 2) + "%"
	}
}

func formatTemperature(value float64) string {
	if value >= 100 {
		return formatFloat(value, 0) + "°C"
	}
	return formatFloat(value, 1) + "°C"
}

func formatPower(value float64) string {
	switch {
	case value >= 1000:
		return formatFloat(value/1000, 1) + "kW"
	case value >= 100:
		return formatFloat(value, 0) + "W"
	default:
		return formatFloat(value, 1) + "W"
	}
}

func formatFrequency(value float64) string {
	switch {
	case value >= 1000:
		return formatFloat(value/1000, 2) + "GHz"
	case value >= 100:
		return formatFloat(value, 0) + "MHz"
	default:
		return formatFloat(value, 1) + "MHz"
	}
}

// formatFloat formats a float with specified decimal places.
func formatFloat(value float64, decimals int) string {
	formatted := strconv.FormatFloat(value, 'f', decimals, 64)

	// Only trim zeros after decimal point, not before it.
	if decimals > 0 && strings.Contains(formatted, ".") {
		// Remove trailing zeros after decimal point.
		formatted = strings.TrimRight(formatted, "0")
		// Remove trailing decimal point if no fractional part remains.
		formatted = strings.TrimRight(formatted, ".")
	}

	if formatted == "" {
		formatted = "0"
	}

	return formatted
}

// formatBytes formats byte values with binary prefixes.
func formatBytes(bytes float64) string {
	units := []string{"B", "KiB", "MiB", "GiB", "TiB"}
	unitIndex := 0
	value := bytes

	for unitIndex < len(units)-1 && value >= 1024 {
		value /= 1024
		unitIndex++
	}

	if unitIndex == 0 {
		return formatFloat(value, 0) + units[unitIndex]
	}
	return formatFloat(value, 1) + units[unitIndex]
}

// formatRate formats rate values (MB/s, GB/s).
func formatRate(value float64, baseUnit string) string {
	// Convert to bytes if needed
	switch baseUnit {
	case "MB":
		value = value * 1024 * 1024
	case "GB":
		value = value * 1024 * 1024 * 1024
	}

	// Now format with decimal prefixes
	if value >= 1e9 {
		return formatFloat(value/1e9, 1) + "GB/s"
	}
	if value >= 1e6 {
		return formatFloat(value/1e6, 1) + "MB/s"
	}
	if value >= 1e3 {
		return formatFloat(value/1e3, 1) + "KB/s"
	}
	return formatFloat(value, 0) + "B/s"
}
