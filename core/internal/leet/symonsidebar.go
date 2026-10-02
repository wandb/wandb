package leet

import (
	"cmp"
	"fmt"
	"math"
	"slices"
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/monitor"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// symonSidebarLabelWidth is the column reserved for row labels, the widest
// being "Disk C:\".
const symonSidebarLabelWidth = 8

// symonSidebar renders the standalone system monitor's vitals: what the
// machine is, then a meter or value line per resource from the latest
// sample, the way htop's header does, and the busiest processes below.
type symonSidebar struct {
	config  *ConfigManager
	visible bool
	probe   SymonProbeMsg

	// procs pages through the processes that match filter, sorted by CPU
	// or by memory. Its cursor is shown while the list has focus.
	procs        PagedList[monitor.ProcessStat]
	filter       *Filter
	sortByMemory bool

	// procRowsTop is the sidebar line of the first process row in the last
	// render, so a click can select one.
	procRowsTop int
}

func newSymonSidebar(config *ConfigManager) *symonSidebar {
	return &symonSidebar{
		config:  config,
		visible: config.SymonSidebarVisible(),
		filter:  NewFilter(),
	}
}

// setProcesses replaces the process table, keeping the sort, the filter
// and the cursor position.
func (sb *symonSidebar) setProcesses(procs []monitor.ProcessStat) {
	sb.procs.Items = procs
	sb.sortProcesses()
}

func (sb *symonSidebar) sortProcesses() {
	slices.SortFunc(sb.procs.Items, func(a, b monitor.ProcessStat) int {
		byCPU := cmp.Compare(b.CPUPercent, a.CPUPercent)
		byMemory := cmp.Compare(b.RSS, a.RSS)
		if sb.sortByMemory {
			return cmp.Or(byMemory, byCPU)
		}
		return cmp.Or(byCPU, byMemory)
	})
	sb.applyProcessFilter()
}

// applyProcessFilter recomputes the visible processes by name or PID.
func (sb *symonSidebar) applyProcessFilter() {
	matcher := sb.filter.Matcher()
	filtered := make([]monitor.ProcessStat, 0, len(sb.procs.Items))
	for _, proc := range sb.procs.Items {
		if matcher(proc.Name) || matcher(strconv.Itoa(int(proc.PID))) {
			filtered = append(filtered, proc)
		}
	}
	sb.procs.FilteredItems = filtered
	sb.procs.SetItemsPerPage(sb.procs.ItemsPerPage())
}

func (sb *symonSidebar) handleProcessFilterKey(msg tea.KeyPressMsg) {
	if sb.filter.HandleKey(msg) {
		sb.applyProcessFilter()
		sb.procs.Home()
	}
}

func (sb *symonSidebar) clearProcessFilter() {
	sb.filter.Clear()
	sb.applyProcessFilter()
	sb.procs.Home()
}

// selectProcessAt moves the cursor to the process row rendered at the
// given sidebar line, if there is one.
func (sb *symonSidebar) selectProcessAt(y int) {
	sb.procs.SetPageAndLine(sb.procs.CurrentPage(), y-sb.procRowsTop)
}

// View renders the sidebar with its right border, highlighted while the
// border is being dragged.
func (sb *symonSidebar) View(width, height int, latest map[string]float64, dragging bool) string {
	contentWidth := sidebarContentWidth(width)

	lines := sb.hostLines(contentWidth)
	if vitals := sb.vitalLines(contentWidth, latest); len(vitals) > 0 {
		if len(lines) > 0 {
			lines = append(lines, "")
		}
		lines = append(lines, vitals...)
	}
	sb.procRowsTop = len(lines) + 3
	if procs := sb.processLines(contentWidth, height-len(lines)-1); len(procs) > 0 {
		lines = append(lines, "")
		lines = append(lines, procs...)
	}

	block := leftSidebarStyle.
		Width(sidebarInnerWidth(width)).
		Height(height).
		MaxHeight(height).
		Render(strings.Join(lines, "\n"))
	if dragging {
		return leftSidebarBorderHighlightStyle.Render(block)
	}
	return leftSidebarBorderStyle.Render(block)
}

// hostLines describes the machine from the probe: chip or CPU model, core
// counts and memory, and the GPUs.
func (sb *symonSidebar) hostLines(width int) []string {
	env := sb.probe.Env
	var lines []string

	if model := cmp.Or(env.GetApple().GetName(), sb.probe.CPUModel); model != "" {
		lines = append(lines, leftSidebarHeaderStyle.Render(truncateValue(model, width)))
	}

	var facts []string
	if n := env.GetCpuCountLogical(); n > 0 {
		cores := fmt.Sprintf("%d cores", n)
		if apple := env.GetApple(); apple.GetPcpuCores() > 0 {
			cores += fmt.Sprintf(" (%dP + %dE)", apple.GetPcpuCores(), apple.GetEcpuCores())
		}
		facts = append(facts, cores)
	}
	if n := env.GetApple().GetGpuCores(); n > 0 {
		facts = append(facts, fmt.Sprintf("%d GPU cores", n))
	}
	if total := env.GetMemory().GetTotal(); total > 0 {
		facts = append(facts, formatBytesBinary(float64(total)))
	}
	if len(facts) > 0 {
		lines = append(lines, labelStyle.Render(truncateValue(strings.Join(facts, " • "), width)))
	}

	if gpus := gpuModels(env); gpus != "" {
		lines = append(lines, labelStyle.Render(truncateValue(gpus, width)))
	}
	return lines
}

// gpuModels lists the discrete GPUs by model, such as "8 × NVIDIA H100".
func gpuModels(env *spb.EnvironmentRecord) string {
	var models []string
	counts := map[string]int{}
	add := func(model string) {
		if model == "" {
			return
		}
		if counts[model] == 0 {
			models = append(models, model)
		}
		counts[model]++
	}
	for _, gpu := range env.GetGpuNvidia() {
		add(gpu.GetName())
	}
	for _, gpu := range env.GetGpuAmd() {
		add(gpu.GetModel())
	}

	parts := make([]string, 0, len(models))
	for _, model := range models {
		if counts[model] > 1 {
			model = fmt.Sprintf("%d × %s", counts[model], model)
		}
		parts = append(parts, model)
	}
	return strings.Join(parts, " • ")
}

// vitalLines renders one row per resource present in the latest sample.
func (sb *symonSidebar) vitalLines(width int, latest map[string]float64) []string {
	if len(latest) == 0 {
		return nil
	}
	meterWidth := clamp(width/3, 8, 24)
	colors := FrenchFriesColors(sb.config.FrenchFriesColorScheme())

	meterRow := func(label string, percent float64, value string) string {
		return symonSidebarRow(width, label,
			renderMeter(meterWidth, percent/100, colors),
			formatPercent(percent)+value)
	}
	textRow := func(label, value string) string {
		return symonSidebarRow(width, label, "", value)
	}
	var lines []string

	if cores := indexedKeys(latest, "cpu.", ".cpu_percent"); len(cores) > 0 {
		var sum float64
		for _, core := range cores {
			sum += latest["cpu."+core+".cpu_percent"]
		}
		value := ""
		if temp, ok := latest["cpu.avg_temp"]; ok {
			value = "  " + formatCelsius(temp)
		}
		lines = append(lines, meterRow("CPU", sum/float64(len(cores)), value))
	}

	if percent, ok := latest["memory_percent"]; ok {
		value := ""
		if total := float64(sb.probe.Env.GetMemory().GetTotal()); total > 0 {
			used, ok := latest["memory.used"]
			if !ok {
				used = total * percent / 100
			}
			value = "  " + formatBytesBinary(used) + " / " + formatBytesBinary(total)
		}
		lines = append(lines, meterRow("Mem", percent, value))
	}

	if percent, ok := latest["swap.used_percent"]; ok {
		value := ""
		if used, ok := latest["swap.used"]; ok && used > 0 {
			value = "  " + formatBytesBinary(used)
		}
		lines = append(lines, meterRow("Swap", percent, value))
	}

	for _, path := range indexedKeys(latest, "disk.", ".usagePercent") {
		lines = append(lines, meterRow("Disk "+path, latest["disk."+path+".usagePercent"], ""))
	}

	for _, gpu := range indexedKeys(latest, "gpu.", ".gpu") {
		var value string
		if temp, ok := latest["gpu."+gpu+".temp"]; ok {
			value += "  " + formatCelsius(temp)
		}
		if mem, ok := latest["gpu."+gpu+".memoryAllocated"]; ok {
			value += "  mem" + formatPercent(mem)
		}
		if watts, ok := latest["gpu."+gpu+".powerWatts"]; ok {
			value += "  " + UnitWatt.Format(watts)
		}
		lines = append(lines, meterRow("GPU "+gpu, latest["gpu."+gpu+".gpu"], value))
	}

	recv, hasRecv := latest["network.recvBps"]
	sent, hasSent := latest["network.sentBps"]
	if hasRecv || hasSent {
		lines = append(lines, textRow("Net",
			"↓ "+UnitBps.Format(recv)+"  ↑ "+UnitBps.Format(sent)))
	}

	if devices := indexedKeys(latest, "disk.", ".readBps"); len(devices) > 0 {
		var read, write float64
		for _, dev := range devices {
			read += latest["disk."+dev+".readBps"]
			write += latest["disk."+dev+".writeBps"]
		}
		lines = append(lines, textRow("I/O",
			"R "+UnitBps.Format(read)+"  W "+UnitBps.Format(write)))
	}

	if watts, ok := latest["system.powerWatts"]; ok {
		lines = append(lines, textRow("Power", UnitWatt.Format(watts)))
	}
	return lines
}

// processLines renders the current page of processes in the rows available
// below the vitals: a title with the page range, a column header and one
// row per process, with the cursor row highlighted while the list has focus.
func (sb *symonSidebar) processLines(width, rows int) []string {
	if len(sb.procs.Items) == 0 || rows < 3 {
		return nil
	}
	sb.procs.SetItemsPerPage(rows - 2)

	sortKey := "CPU"
	if sb.sortByMemory {
		sortKey = "memory"
	}
	title := leftSidebarHeaderStyle.Render("Top processes by " + sortKey)
	lines := []string{
		title + navInfoStyle.Render(truncateValue(
			sb.processNavInfo(), max(width-lipgloss.Width(title), 0))),
		runOverviewSidebarKeyStyle.Render(truncateValue(
			fmt.Sprintf("%7s %6s %8s  %s", "PID", "CPU%", "MEM", "COMMAND"), width)),
	}
	start, end := sb.procs.PageBounds()
	for i := start; i < end; i++ {
		proc := sb.procs.FilteredItems[i]
		line := truncateValue(fmt.Sprintf("%7d %6.1f %8s  %s",
			proc.PID, proc.CPUPercent, formatBytesBinary(float64(proc.RSS)), proc.Name), width)
		if sb.procs.Active && i-start == sb.procs.CurrentLine() {
			lines = append(lines, runOverviewSidebarHighlightedItem.Width(width).Render(line))
		} else {
			lines = append(lines, runOverviewSidebarValueStyle.Render(line))
		}
	}
	return lines
}

// processNavInfo reports the visible range of processes, and the filter's
// effect when one is set.
func (sb *symonSidebar) processNavInfo() string {
	total := len(sb.procs.Items)
	filtered := len(sb.procs.FilteredItems)
	start, end := sb.procs.PageBounds()
	if filtered == 0 {
		return fmt.Sprintf(" [0 of %d]", total)
	}
	if filtered != total {
		return fmt.Sprintf(" [%d-%d of %d filtered from %d]", start+1, end, filtered, total)
	}
	return fmt.Sprintf(" [%d-%d of %d]", start+1, end, total)
}

// symonSidebarRow lays out a label column, an optional meter and the value
// text, truncated to the row width.
func symonSidebarRow(width int, label, meter, value string) string {
	if meter != "" {
		meter += " "
	}
	rest := max(width-symonSidebarLabelWidth-lipgloss.Width(meter), 0)
	if rest <= 3 {
		value = ""
	}
	return runOverviewSidebarKeyStyle.Width(symonSidebarLabelWidth).Render(label) +
		meter + runOverviewSidebarValueStyle.Render(truncateValue(value, rest))
}

// renderMeter draws a bar filled to frac, colored cell by cell from the
// heatmap palette so a full bar reads as hot.
func renderMeter(width int, frac float64, colors []AdaptiveColor) string {
	filled := int(math.Round(min(max(frac, 0), 1) * float64(width)))
	var b strings.Builder
	for i := range width {
		if i < filled {
			b.WriteString(lipgloss.NewStyle().
				Foreground(colors[i*len(colors)/width]).
				Render(frenchFriesCell))
		} else {
			b.WriteString(axisStyle.Render("░"))
		}
	}
	return b.String()
}

// indexedKeys returns the middle segments of the keys prefix + segment +
// suffix, with numeric segments in numeric order.
func indexedKeys(latest map[string]float64, prefix, suffix string) []string {
	var segments []string
	for key := range latest {
		segment, ok := strings.CutPrefix(key, prefix)
		if !ok {
			continue
		}
		segment, ok = strings.CutSuffix(segment, suffix)
		if ok && !strings.Contains(segment, ".") {
			segments = append(segments, segment)
		}
	}
	slices.SortFunc(segments, func(a, b string) int {
		ai, aErr := strconv.Atoi(a)
		bi, bErr := strconv.Atoi(b)
		if aErr == nil && bErr == nil {
			return cmp.Compare(ai, bi)
		}
		return strings.Compare(a, b)
	})
	return segments
}

func formatPercent(v float64) string { return fmt.Sprintf("%3.0f%%", v) }

func formatCelsius(v float64) string { return fmt.Sprintf("%.0f°C", v) }
