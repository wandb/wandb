package leet

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

type ConfigEditorParams struct {
	Config *ConfigManager
	Logger *observability.CoreLogger
}

// ConfigEditor is a standalone Bubble Tea model for editing leet config.
//
// Implements tea.Model.
type ConfigEditor struct {
	cfg    *ConfigManager
	logger *observability.CoreLogger

	original Config
	draft    Config

	fields   []configField
	selected int

	width  int
	height int

	mode editorMode

	enum enumSelectState
	intE intEditState

	confirmQuit bool
	status      string
}

func NewConfigEditor(params ConfigEditorParams) *ConfigEditor {
	logger := params.Logger
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}

	cfg := params.Config
	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	orig := cfg.Snapshot()

	return &ConfigEditor{
		cfg:      cfg,
		logger:   logger,
		original: orig,
		draft:    orig,
		fields:   buildConfigEditorFields(),
		selected: 0,
		mode:     modeBrowse,
	}
}

type editorMode int

const (
	modeUnknown editorMode = iota
	modeBrowse
	modeEnumSelect
	modeIntEdit
)

type configFieldKind int

const (
	fieldUnknown configFieldKind = iota
	fieldBool
	fieldInt
	fieldEnum
)

type configField struct {
	Label       string
	JSONKey     string
	Description string
	Kind        configFieldKind

	// bool
	getBool func(Config) bool
	setBool func(*Config, bool)

	// int
	getInt func(Config) int
	setInt func(*Config, int)
	min    int
	max    int // 0 => no max

	// enum
	options []string
	getEnum func(Config) string
	setEnum func(*Config, string)
}

type enumSelectState struct {
	fieldIndex int
	options    []string
	index      int
}

type intEditState struct {
	fieldIndex int
	input      string
	err        string
}

func (m *ConfigEditor) Init() tea.Cmd { return nil }

func (m *ConfigEditor) dirty() bool {
	return m.draft != m.original
}

func (m *ConfigEditor) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil
	case tea.KeyMsg:
		// Any key other than quit/save clears quit confirmation.
		if msg.String() != "q" && msg.String() != "esc" {
			m.confirmQuit = false
		}

		switch m.mode {
		case modeEnumSelect:
			return m.updateEnumSelect(msg)
		case modeIntEdit:
			return m.updateIntEdit(msg)
		case modeBrowse:
			return m.updateBrowse(msg)
		default:
			return m, nil
		}
	default:
		return m, nil
	}
}

func (m *ConfigEditor) updateBrowse(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "ctrl+c":
		if m.dirty() && !m.confirmQuit {
			m.confirmQuit = true
			m.status = "Unsaved changes — press q again to discard, or s to save & quit."
			return m, nil
		}
		return m, tea.Quit
	case "q", "esc":
		if m.dirty() && !m.confirmQuit {
			m.confirmQuit = true
			m.status = "Unsaved changes — press q again to discard, or s to save & quit."
			return m, nil
		}
		return m, tea.Quit
	case "s", "ctrl+s":
		if err := m.cfg.SetConfig(m.draft); err != nil {
			m.status = fmt.Sprintf("Save failed: %v", err)
			return m, nil
		}
		return m, tea.Quit
	case "up", "k":
		if m.selected > 0 {
			m.selected--
		}
		return m, nil
	case "down", "j":
		if m.selected < len(m.fields)-1 {
			m.selected++
		}
		return m, nil
	case "left", "h":
		m.bumpSelected(-1)
		return m, nil
	case "right", "l":
		m.bumpSelected(1)
		return m, nil
	case "enter":
		return m.activateSelected()
	case " ":
		// Space toggles bools; otherwise acts like enter.
		f := m.fields[m.selected]
		if f.Kind == fieldBool {
			cur := f.getBool(m.draft)
			f.setBool(&m.draft, !cur)
			return m, nil
		}
		return m.activateSelected()
	default:
		return m, nil
	}
}

func (m *ConfigEditor) activateSelected() (tea.Model, tea.Cmd) {
	f := m.fields[m.selected]
	switch f.Kind {
	case fieldBool:
		cur := f.getBool(m.draft)
		f.setBool(&m.draft, !cur)
		return m, nil
	case fieldEnum:
		opts := f.options
		if len(opts) == 0 {
			return m, nil
		}
		cur := f.getEnum(m.draft)
		idx := max(indexOf(opts, cur), 0)
		m.mode = modeEnumSelect
		m.enum = enumSelectState{
			fieldIndex: m.selected,
			options:    opts,
			index:      idx,
		}
		return m, nil
	case fieldInt:
		cur := f.getInt(m.draft)
		m.mode = modeIntEdit
		m.intE = intEditState{
			fieldIndex: m.selected,
			input:      strconv.Itoa(cur),
		}
		return m, nil
	default:
		return m, nil
	}
}

func (m *ConfigEditor) bumpSelected(delta int) {
	f := m.fields[m.selected]
	switch f.Kind {
	case fieldEnum:
		opts := f.options
		if len(opts) == 0 {
			return
		}
		cur := f.getEnum(m.draft)
		idx := max(indexOf(opts, cur), 0)
		idx = (idx + delta) % len(opts)
		if idx < 0 {
			idx += len(opts)
		}
		f.setEnum(&m.draft, opts[idx])
	case fieldInt:
		cur := f.getInt(m.draft)
		next := max(cur+delta, f.min)
		if f.max > 0 && next > f.max {
			next = f.max
		}
		f.setInt(&m.draft, next)
	case fieldBool:
		cur := f.getBool(m.draft)
		f.setBool(&m.draft, !cur)
	default:
	}
}

func (m *ConfigEditor) updateEnumSelect(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = modeBrowse
		m.enum = enumSelectState{}
		return m, nil
	case "enter":
		f := m.fields[m.enum.fieldIndex]
		if m.enum.index >= 0 && m.enum.index < len(m.enum.options) {
			f.setEnum(&m.draft, m.enum.options[m.enum.index])
		}
		m.mode = modeBrowse
		m.enum = enumSelectState{}
		return m, nil
	case "up", "k":
		if m.enum.index > 0 {
			m.enum.index--
		}
		return m, nil
	case "down", "j":
		if m.enum.index < len(m.enum.options)-1 {
			m.enum.index++
		}
		return m, nil
	default:
		return m, nil
	}
}

func (m *ConfigEditor) updateIntEdit(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = modeBrowse
		m.intE = intEditState{}
		return m, nil
	case "enter":
		f := m.fields[m.intE.fieldIndex]
		raw := strings.TrimSpace(m.intE.input)
		val, err := strconv.Atoi(raw)
		if err != nil {
			m.intE.err = "Invalid integer"
			return m, nil
		}
		if val < f.min {
			m.intE.err = fmt.Sprintf("Must be >= %d", f.min)
			return m, nil
		}
		if f.max > 0 && val > f.max {
			m.intE.err = fmt.Sprintf("Must be <= %d", f.max)
			return m, nil
		}
		f.setInt(&m.draft, val)
		m.mode = modeBrowse
		m.intE = intEditState{}
		return m, nil
	case "backspace":
		if len(m.intE.input) == 0 {
			return m, nil
		}
		m.intE.input = m.intE.input[:len(m.intE.input)-1]
		m.intE.err = ""
		return m, nil
	default:
		if msg.Type == tea.KeyRunes {
			for _, r := range msg.Runes {
				if unicode.IsDigit(r) {
					m.intE.input += string(r)
					m.intE.err = ""
				}
			}
		}
		return m, nil
	}
}

func (m *ConfigEditor) View() string {
	w := m.width
	if w <= 0 {
		w = 80
	}

	title := "W&B LEET Config"
	if m.dirty() {
		title += " *"
	}

	top := lipgloss.JoinVertical(
		lipgloss.Left,
		headerStyle.Render(title),
		navInfoStyle.Render(fmt.Sprintf("Path: %s", m.cfg.Path())),
	)

	table := m.renderTable(w)

	footer := m.renderFooter(w)

	view := lipgloss.JoinVertical(lipgloss.Left, top, "", table, "", footer)

	// Inline "modal" area for edit states.
	switch m.mode {
	case modeEnumSelect:
		view = lipgloss.JoinVertical(lipgloss.Left, view, "", m.renderEnumPicker(w))
	case modeIntEdit:
		view = lipgloss.JoinVertical(lipgloss.Left, view, "", m.renderIntEditor(w))
	}

	return lipgloss.NewStyle().Padding(1, 2).Render(view)
}

func (m *ConfigEditor) renderTable(width int) string {
	// Column widths.
	maxLabel := 0
	for _, f := range m.fields {
		if lw := lipgloss.Width(f.Label); lw > maxLabel {
			maxLabel = lw
		}
	}
	keyW := min(maxLabel, max(20, width/2))
	valW := max(12, width-keyW-3)

	headerLine := lipgloss.JoinHorizontal(
		lipgloss.Left,
		lipgloss.NewStyle().Width(keyW).Bold(true).Render("Setting"),
		"   ",
		lipgloss.NewStyle().Width(valW).Bold(true).Render("Value"),
	)

	var lines []string
	lines = append(lines, headerLine)

	for i, f := range m.fields {
		val := fieldValue(f, m.draft)
		val = truncateRight(val, valW)

		line := lipgloss.JoinHorizontal(
			lipgloss.Left,
			lipgloss.NewStyle().Width(keyW).Render(f.Label),
			"   ",
			lipgloss.NewStyle().Width(valW).Render(val),
		)

		if i == m.selected {
			line = lipgloss.NewStyle().
				Width(width).
				Background(colorSelected).
				Render(line)
		}
		lines = append(lines, line)
	}

	return strings.Join(lines, "\n")
}

func (m *ConfigEditor) renderFooter(width int) string {
	var parts []string

	if m.status != "" {
		parts = append(parts, statusBarStyle.Width(width).Render(m.status))
	}

	f := m.fields[m.selected]
	desc := fmt.Sprintf("%s  (%s)", f.Description, f.JSONKey)
	parts = append(parts, navInfoStyle.Width(width).Render(desc))

	help := "↑/↓ select • Enter edit • ←/→ adjust • s save & quit • q quit"
	parts = append(parts, navInfoStyle.Width(width).Render(help))

	return strings.Join(parts, "\n")
}

func (m *ConfigEditor) renderEnumPicker(width int) string {
	f := m.fields[m.enum.fieldIndex]

	var lines []string
	lines = append(lines, headerStyle.Render(fmt.Sprintf("Select %s", f.Label)))
	lines = append(lines, navInfoStyle.Render("Enter: apply • Esc: cancel"))

	for i, opt := range m.enum.options {
		prefix := "  "
		if i == m.enum.index {
			prefix = "> "
		}
		lines = append(lines, prefix+opt)
	}

	box := lipgloss.NewStyle().
		Width(min(width, 80)).
		Border(lipgloss.RoundedBorder()).
		Padding(1, 2).
		Render(strings.Join(lines, "\n"))

	return box
}

func (m *ConfigEditor) renderIntEditor(width int) string {
	f := m.fields[m.intE.fieldIndex]
	hint := "Enter: apply • Esc: cancel"
	rangeHint := ""
	if f.max > 0 {
		rangeHint = fmt.Sprintf("Range: %d..%d", f.min, f.max)
	} else {
		rangeHint = fmt.Sprintf("Min: %d", f.min)
	}

	var lines []string
	lines = append(lines, headerStyle.Render(fmt.Sprintf("Edit %s", f.Label)))
	lines = append(lines, navInfoStyle.Render(rangeHint))
	lines = append(lines, navInfoStyle.Render(hint))
	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("> %s", m.intE.input))
	if m.intE.err != "" {
		lines = append(lines, "")
		lines = append(lines, errorStyle.Render(m.intE.err))
	}

	box := lipgloss.NewStyle().
		Width(min(width, 80)).
		Border(lipgloss.RoundedBorder()).
		Padding(1, 2).
		Render(strings.Join(lines, "\n"))

	return box
}

func buildConfigEditorFields() []configField {
	schemes := availableColorSchemes()
	modes := []string{ColorModePerSeries, ColorModePerPlot}

	return []configField{
		{
			Label:       "Metrics grid rows",
			JSONKey:     "metrics_grid.rows",
			Description: "Rows in the main metrics grid.",
			Kind:        fieldInt,
			getInt:      func(c Config) int { return c.MetricsGrid.Rows },
			setInt:      func(c *Config, v int) { c.MetricsGrid.Rows = v },
			min:         1,
			max:         9,
		},
		{
			Label:       "Metrics grid cols",
			JSONKey:     "metrics_grid.cols",
			Description: "Columns in the main metrics grid.",
			Kind:        fieldInt,
			getInt:      func(c Config) int { return c.MetricsGrid.Cols },
			setInt:      func(c *Config, v int) { c.MetricsGrid.Cols = v },
			min:         1,
			max:         9,
		},
		{
			Label:       "System grid rows",
			JSONKey:     "system_grid.rows",
			Description: "Rows in the system metrics grid.",
			Kind:        fieldInt,
			getInt:      func(c Config) int { return c.SystemGrid.Rows },
			setInt:      func(c *Config, v int) { c.SystemGrid.Rows = v },
			min:         1,
			max:         9,
		},
		{
			Label:       "System grid cols",
			JSONKey:     "system_grid.cols",
			Description: "Columns in the system metrics grid.",
			Kind:        fieldInt,
			getInt:      func(c Config) int { return c.SystemGrid.Cols },
			setInt:      func(c *Config, v int) { c.SystemGrid.Cols = v },
			min:         1,
			max:         9,
		},
		{
			Label:       "Color scheme",
			JSONKey:     "color_scheme",
			Description: "Palette for main run metrics charts (and run list colors).",
			Kind:        fieldEnum,
			options:     schemes,
			getEnum:     func(c Config) string { return c.ColorScheme },
			setEnum:     func(c *Config, v string) { c.ColorScheme = v },
		},
		{
			Label:       "Per-plot color scheme",
			JSONKey:     "per_plot_color_scheme",
			Description: "Palette for single-run view in per-plot mode. Gradients look nice here.",
			Kind:        fieldEnum,
			options:     schemes,
			getEnum:     func(c Config) string { return c.PerPlotColorScheme },
			setEnum:     func(c *Config, v string) { c.PerPlotColorScheme = v },
		},
		{
			Label:       "System color scheme",
			JSONKey:     "system_color_scheme",
			Description: "Palette for system charts.",
			Kind:        fieldEnum,
			options:     schemes,
			getEnum:     func(c Config) string { return c.SystemColorScheme },
			setEnum:     func(c *Config, v string) { c.SystemColorScheme = v },
		},
		{
			Label:       "System color mode",
			JSONKey:     "system_color_mode",
			Description: "Color system charts per plot or per series.",
			Kind:        fieldEnum,
			options:     modes,
			getEnum:     func(c Config) string { return c.SystemColorMode },
			setEnum:     func(c *Config, v string) { c.SystemColorMode = v },
		},
		{
			Label:       "Single-run color mode",
			JSONKey:     "single_run_color_mode",
			Description: "Color single-run charts per plot or use stable run-id color for all.",
			Kind:        fieldEnum,
			options:     modes,
			getEnum:     func(c Config) string { return c.SingleRunColorMode },
			setEnum:     func(c *Config, v string) { c.SingleRunColorMode = v },
		},
		{
			Label:       "Heartbeat interval (sec)",
			JSONKey:     "heartbeat_interval_seconds",
			Description: "Polling heartbeat for live runs.",
			Kind:        fieldInt,
			getInt:      func(c Config) int { return c.HeartbeatInterval },
			setInt:      func(c *Config, v int) { c.HeartbeatInterval = v },
			min:         1,
			max:         0,
		},
		{
			Label:       "Left sidebar visible",
			JSONKey:     "left_sidebar_visible",
			Description: "Show left sidebar by default.",
			Kind:        fieldBool,
			getBool:     func(c Config) bool { return c.LeftSidebarVisible },
			setBool:     func(c *Config, v bool) { c.LeftSidebarVisible = v },
		},
		{
			Label:       "Right sidebar visible",
			JSONKey:     "right_sidebar_visible",
			Description: "Show right sidebar by default.",
			Kind:        fieldBool,
			getBool:     func(c Config) bool { return c.RightSidebarVisible },
			setBool:     func(c *Config, v bool) { c.RightSidebarVisible = v },
		},
	}
}

func availableColorSchemes() []string {
	names := make([]string, 0, len(colorSchemes))
	for name := range colorSchemes {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func fieldValue(f configField, c Config) string {
	switch f.Kind {
	case fieldBool:
		return strconv.FormatBool(f.getBool(c))
	case fieldInt:
		return strconv.Itoa(f.getInt(c))
	case fieldEnum:
		return f.getEnum(c)
	default:
		return ""
	}
}

func indexOf(opts []string, v string) int {
	for i := range opts {
		if opts[i] == v {
			return i
		}
	}
	return -1
}

func truncateRight(s string, maxW int) string {
	if maxW <= 0 || lipgloss.Width(s) <= maxW {
		return s
	}
	if maxW <= 3 {
		return "..."
	}
	// Simple rune-safe truncation with ellipsis.
	r := []rune(s)
	out := string(r)
	for lipgloss.Width(out) > maxW-3 && len(r) > 0 {
		r = r[:len(r)-1]
		out = string(r)
	}
	return out + "..."
}
