package leet

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"unicode"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	quitConfirmStatusBrowse = "Unsaved changes — press q/esc/ctrl+c again to discard, or s to save & quit."
	quitConfirmStatusEdit   = "Unsaved changes — press q/ctrl+c again to discard, or Esc to keep editing."

	ConfigEditorPalettePreviewBlock = "█"
)

// ConfigEditorParams configures a [ConfigEditor].
type ConfigEditorParams struct {
	// Config is the config manager to read from and persist to.
	// If nil, a default manager is created from the standard config path.
	Config *ConfigManager

	// Logger is used for error reporting.
	// If nil, a no-op logger is used.
	Logger *observability.CoreLogger
}

// ConfigEditor is a standalone Bubble Tea model for interactively editing
// LEET's persisted configuration.
//
// Launch it with `wandb beta leet config`. It reads the current config from
// disk, presents every editable field in a navigable table, and writes changes
// back atomically on save.
//
// # Schema derivation
//
// The editor schema is derived from the [Config] struct at init time via
// [buildConfigEditorFields]. Supported field types are bool, int, and
// string enums (string fields must declare an enum provider via
// `leet:"options=<provider>"`). See [configeditorfields.go] for the full
// tag grammar and reflection logic.
//
// # Modes
//
// The editor operates in one of three modes:
//
//   - Browse: navigate settings with ↑/↓, quick-adjust with ←/→,
//     toggle bools with Space, or press Enter to open a type-specific
//     sub-editor.
//   - Enum select: pick from a list of allowed values (opened from
//     enum fields).
//   - Int edit: type a numeric value with validation against min/max
//     constraints (opened from int fields).
//
// # Key bindings
//
// Browse mode:
//   - ↑/↓ or k/j: select setting
//   - Enter: open sub-editor for the selected field
//   - ←/→ or h/l: quick-adjust (toggle bool, bump int, cycle enum)
//   - Space: toggle bool (otherwise acts like Enter)
//   - s / ctrl+s: save and quit
//   - q / esc / ctrl+c: quit (prompts if there are unsaved changes)
//
// Enum select / Int edit:
//   - Enter: apply
//   - Esc: cancel (return to browse)
//
// Implements [tea.Model].
type ConfigEditor struct {
	// cfg is the config manager used to read the initial snapshot and
	// persist changes on save.
	cfg    *ConfigManager
	logger *observability.CoreLogger

	// original holds the config snapshot taken at editor creation.
	// Compared with draft to detect unsaved changes.
	original Config

	// draft is the working copy that the user edits. On save it is
	// written to disk via cfg; on quit it is discarded.
	draft Config

	// fields is the flat list of editable settings derived from [Config]
	// struct tags. See [buildConfigEditorFields].
	fields []configField

	// selected is the index into fields of the currently highlighted row.
	selected int

	// width and height cache the latest terminal dimensions for layout.
	width  int
	height int

	// mode is the current interaction state (browse, enum select, or int edit).
	mode editorMode

	// enum holds transient state for the enum picker modal (active when
	// mode == modeEnumSelect).
	enum enumSelectState

	// intE holds transient state for the integer input modal (active when
	// mode == modeIntEdit).
	intE intEditState

	// confirmQuit is set after the first quit attempt with unsaved changes.
	// A second quit attempt while confirmQuit is true exits unconditionally.
	confirmQuit bool

	// status is an ephemeral message shown in the footer (e.g. unsaved
	// changes warning, save-failure error). Cleared on the next key press.
	status string
}

// NewConfigEditor creates a [ConfigEditor] from the given params.
//
// It snapshots the current config from disk and builds the editable field
// schema via [buildConfigEditorFields]. If no editable fields are found
// (indicating a schema bug), an error is logged but the editor is still
// returned so the caller sees the empty-state UI.
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
	fields := buildConfigEditorFields()
	if len(fields) == 0 {
		logger.Error("config editor: no editable config fields found")
	}

	return &ConfigEditor{
		cfg:      cfg,
		logger:   logger,
		original: orig,
		draft:    orig,
		fields:   fields,
		selected: 0,
		mode:     modeBrowse,
	}
}

// editorMode tracks which interaction state the editor is in.
type editorMode int

const (
	modeUnknown editorMode = iota
	modeBrowse
	modeEnumSelect
	modeIntEdit
)

// configFieldKind distinguishes the three supported field types.
type configFieldKind int

const (
	fieldUnknown configFieldKind = iota
	fieldBool
	fieldInt
	fieldEnum
)

// enumProvider identifies a registered options source for enum fields.
//
// Provider names appear in struct tags as `leet:"options=<name>"`;
// [parseEnumProvider] converts the tag string to a typed constant, and
// [enumProvider.options] returns the allowed values. Adding a new enum
// field requires a new constant here and a case in each of those two
// functions.
type enumProvider int

const (
	enumProviderUndefined    enumProvider = iota
	enumProviderColorSchemes              // color palette names
	enumProviderColorModes                // per_series | per_plot
	enumProviderStartupModes              // workspace_latest | single_run_latest
)

// options returns the allowed values for this provider.
//
// Returns nil for [enumProviderUndefined], which causes the field to be
// skipped during schema construction.
func (p enumProvider) options() []string {
	switch p {
	case enumProviderColorSchemes:
		return availableColorSchemes()
	case enumProviderColorModes:
		return []string{ColorModePerSeries, ColorModePerPlot}
	case enumProviderStartupModes:
		return []string{StartupModeWorkspaceLatest, StartupModeSingleRunLatest}
	default:
		return nil
	}
}

// configField describes a single editable setting.
//
// Each field carries typed getter/setter closures that operate on
// [Config] values by index path, plus display metadata (label,
// description, JSON key) and type-specific constraints (min/max
// for ints, allowed options for enums).
type configField struct {
	// Label is the human-readable name shown in the settings table
	// (e.g. "Metrics grid rows").
	Label string

	// JSONKey is the dot-joined config path used in the footer and for
	// identifying the field in tests (e.g. "metrics_grid.rows").
	JSONKey string

	// Description is the help text shown in the footer when this field
	// is selected.
	Description string

	// Kind indicates the field type and determines which getter/setter
	// pair and sub-editor are used.
	Kind configFieldKind

	// getBool and setBool are the typed accessors for bool fields.
	getBool func(Config) bool
	setBool func(*Config, bool)

	// getInt and setInt are the typed accessors for int fields.
	getInt func(Config) int
	setInt func(*Config, int)

	// min is the lower bound for int fields (default 0).
	min int

	// max is the upper bound for int fields. Zero means no upper bound.
	max int

	// options lists the allowed values for enum fields, populated at init
	// time by calling [enumProvider.options] on the provider.
	options []string

	// provider identifies which [enumProvider] produced options. Used by
	// [configField.showsColorSchemePreview] to decide whether to render
	// palette swatches in the enum picker.
	provider enumProvider

	// getEnum and setEnum are the typed accessors for enum (string) fields.
	getEnum func(Config) string
	setEnum func(*Config, string)
}

// enumSelectState holds transient state while the user picks from an
// enum's allowed values.
type enumSelectState struct {
	// fieldIndex is the index into [ConfigEditor.fields] for the field
	// being edited.
	fieldIndex int

	// options is a copy of the field's allowed values, displayed in the
	// picker list.
	options []string

	// index is the currently highlighted option within options.
	index int
}

// intEditState holds transient state while the user types an integer value.
type intEditState struct {
	// fieldIndex is the index into [ConfigEditor.fields] for the field
	// being edited.
	fieldIndex int

	// input is the raw digit string the user has typed so far.
	input string

	// err is a validation message shown below the input (e.g. "Must be >= 1").
	// Empty when the input is valid or not yet submitted.
	err string
}

// Init implements [tea.Model]. No initial commands are needed.
func (m *ConfigEditor) Init() tea.Cmd { return nil }

// dirty reports whether the draft diverges from the on-disk snapshot.
func (m *ConfigEditor) dirty() bool {
	return m.draft != m.original
}

// Update implements [tea.Model].
//
// It handles terminal resize events and dispatches key presses to the
// active mode handler. Global quit keys (q, esc, ctrl+c) and save keys
// (s, ctrl+s) are processed before mode-specific handlers.
func (m *ConfigEditor) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil
	case tea.KeyPressMsg:
		key := msg.String()

		// Global quit keys.
		if key == "ctrl+c" || key == "q" || (key == "esc" && m.mode == modeBrowse) {
			return m.handleQuit()
		}

		// Save & quit only from browse mode. (In edit modes, Enter applies changes;
		// this avoids the surprising behavior of saving a half-edited int input.)
		if m.mode == modeBrowse && (key == "s" || key == "ctrl+s") {
			return m.handleSave()
		}

		// Any other key cancels quit confirmation.
		if m.confirmQuit {
			m.confirmQuit = false
			m.status = ""
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

// handleQuit processes a quit request.
//
// If the draft has unsaved changes and this is the first quit attempt, the
// editor enters a confirmation state with a status-bar warning. A second
// quit attempt proceeds unconditionally.
func (m *ConfigEditor) handleQuit() (tea.Model, tea.Cmd) {
	if m.dirty() && !m.confirmQuit {
		m.confirmQuit = true
		if m.mode == modeBrowse {
			m.status = quitConfirmStatusBrowse
		} else {
			m.status = quitConfirmStatusEdit
		}
		return m, nil
	}
	return m, tea.Quit
}

// handleSave persists the draft to disk and exits.
//
// On write failure, the error is logged and displayed in the status bar
// without quitting, giving the user a chance to retry or discard.
func (m *ConfigEditor) handleSave() (tea.Model, tea.Cmd) {
	if err := m.cfg.SetConfig(&m.draft); err != nil {
		m.logger.Error(fmt.Sprintf("config editor: save failed: %v", err))
		m.status = fmt.Sprintf("Save failed: %v", err)
		return m, nil
	}
	return m, tea.Quit
}

// updateBrowse handles key presses in browse mode: cursor movement,
// quick-adjust via arrow keys, and field activation via Enter/Space.
func (m *ConfigEditor) updateBrowse(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	if len(m.fields) == 0 {
		return m, nil
	}

	switch msg.String() {
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
		f := &m.fields[m.selected]
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

// activateSelected opens the appropriate sub-editor for the selected field.
//
// Bool fields are toggled inline without entering a sub-editor. Enum fields
// open the enum picker modal, and int fields open the numeric input modal.
func (m *ConfigEditor) activateSelected() (tea.Model, tea.Cmd) {
	f := &m.fields[m.selected]
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

// bumpSelected applies a quick in-place adjustment to the selected field.
//
// For enums the value cycles through options; for ints it increments or
// decrements within [min, max]; for bools it toggles.
func (m *ConfigEditor) bumpSelected(delta int) {
	if len(m.fields) == 0 {
		return
	}

	f := &m.fields[m.selected]
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

// updateEnumSelect handles key presses in the enum picker modal.
//
// Up/Down navigate the option list, Enter applies the selection, and
// Esc cancels back to browse mode without changing the value.
func (m *ConfigEditor) updateEnumSelect(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = modeBrowse
		m.enum = enumSelectState{}
		return m, nil
	case "enter":
		if m.enum.fieldIndex < 0 || m.enum.fieldIndex >= len(m.fields) {
			m.mode = modeBrowse
			m.enum = enumSelectState{}
			return m, nil
		}
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

// updateIntEdit handles key presses in the integer input modal.
//
// Digit keys append to the input buffer, Backspace removes the last
// character, Enter validates against [configField.min]/[configField.max]
// and applies on success, and Esc cancels without applying.
func (m *ConfigEditor) updateIntEdit(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "esc":
		m.mode = modeBrowse
		m.intE = intEditState{}
		return m, nil
	case "enter":
		if m.intE.fieldIndex < 0 || m.intE.fieldIndex >= len(m.fields) {
			m.mode = modeBrowse
			m.intE = intEditState{}
			return m, nil
		}
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
		if m.intE.input == "" {
			return m, nil
		}
		m.intE.input = m.intE.input[:len(m.intE.input)-1]
		m.intE.err = ""
		return m, nil
	default:
		if msg.Text != "" {
			for _, r := range msg.Text {
				if unicode.IsDigit(r) {
					m.intE.input += string(r)
					m.intE.err = ""
				}
			}
		}
		return m, nil
	}
}

// View implements [tea.Model].
//
// The layout is a vertical stack: header (title + config path), settings
// table, footer (status/description/key hints), and an optional sub-editor
// overlay for enum or int fields. The view uses alt-screen mode.
func (m *ConfigEditor) View() tea.View {
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

	switch m.mode {
	case modeEnumSelect:
		view = lipgloss.JoinVertical(lipgloss.Left, view, "", m.renderEnumPicker(w))
	case modeIntEdit:
		view = lipgloss.JoinVertical(lipgloss.Left, view, "", m.renderIntEditor(w))
	}

	v := tea.NewView(lipgloss.NewStyle().Padding(1, 2).Render(view))
	v.AltScreen = true
	return v
}

// renderTable renders the two-column settings table (Setting | Value).
//
// The selected row is highlighted with [colorSelected]. Column widths
// adapt to the longest label and available terminal width.
func (m *ConfigEditor) renderTable(width int) string {
	// Column widths.
	maxLabel := 0
	for i := range m.fields {
		if lw := lipgloss.Width(m.fields[i].Label); lw > maxLabel {
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

	if len(m.fields) == 0 {
		lines = append(lines, navInfoStyle.Width(width).Render("No editable config fields found."))
		return strings.Join(lines, "\n")
	}

	for i := range m.fields {
		f := &m.fields[i]
		val := fieldValue(f, &m.draft)
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
				Foreground(colorDark).
				Render(line)
		}
		lines = append(lines, line)
	}

	return strings.Join(lines, "\n")
}

// renderFooter renders the bottom section: an optional status bar, the
// selected field's description and JSON key, and the key-binding hints.
func (m *ConfigEditor) renderFooter(width int) string {
	var parts []string

	if m.status != "" {
		parts = append(parts, statusBarStyle.Width(width).Render(m.status))
	}

	if len(m.fields) > 0 && m.selected >= 0 && m.selected < len(m.fields) {
		f := m.fields[m.selected]
		desc := fmt.Sprintf("%s  (%s)", f.Description, f.JSONKey)
		parts = append(parts, navInfoStyle.Width(width).Render(desc))
	}

	help := "↑/↓ select • Enter edit • ←/→ adjust • s save & quit • q/esc/ctrl+c quit"
	parts = append(parts, navInfoStyle.Width(width).Render(help))

	return strings.Join(parts, "\n")
}

// renderEnumPicker renders the bordered modal for choosing among an
// enum field's allowed values. Color scheme fields additionally show
// inline palette swatches via [renderColorSchemePreview].
func (m *ConfigEditor) renderEnumPicker(width int) string {
	f := m.fields[m.enum.fieldIndex]

	var lines []string
	lines = append(
		lines,
		headerStyle.Render(fmt.Sprintf("Select %s", f.Label)),
		navInfoStyle.Render("Enter: apply • Esc: cancel"),
	)

	for i, opt := range m.enum.options {
		prefix := "  "
		if i == m.enum.index {
			prefix = "> "
		}

		line := prefix + opt
		if f.showsColorSchemePreview() {
			line += "  " + renderColorSchemePreview(opt)
		}
		lines = append(lines, line)
	}

	box := lipgloss.NewStyle().
		Width(min(width, 80)).
		Border(lipgloss.RoundedBorder()).
		Padding(1, 2).
		Render(strings.Join(lines, "\n"))

	return box
}

// showsColorSchemePreview reports whether this field's enum picker should
// display inline color swatches next to each option.
func (f *configField) showsColorSchemePreview() bool {
	return f != nil && f.Kind == fieldEnum && f.provider == enumProviderColorSchemes
}

// renderColorSchemePreview returns a compact swatch strip for a palette.
//
// Each block is rendered with the scheme's AdaptiveColor, so lipgloss resolves
// the light or dark variant automatically for the current terminal theme.
func renderColorSchemePreview(scheme string) string {
	colors := GraphColors(scheme)
	if len(colors) == 0 {
		return ""
	}

	var b strings.Builder
	for _, c := range colors {
		b.WriteString(
			lipgloss.NewStyle().Foreground(c).Render(ConfigEditorPalettePreviewBlock))
	}
	return b.String()
}

// renderIntEditor renders the bordered modal for typing an integer value,
// including the allowed range hint and any validation error.
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
	lines = append(lines, headerStyle.Render(fmt.Sprintf("Edit %s", f.Label)),
		navInfoStyle.Render(rangeHint),
		navInfoStyle.Render(hint),
		"",
		fmt.Sprintf("> %s", m.intE.input),
	)
	if m.intE.err != "" {
		lines = append(lines, "", errorStyle.Render(m.intE.err))
	}

	box := lipgloss.NewStyle().
		Width(min(width, 80)).
		Border(lipgloss.RoundedBorder()).
		Padding(1, 2).
		Render(strings.Join(lines, "\n"))

	return box
}

// availableColorSchemes returns the sorted names of all registered color schemes.
func availableColorSchemes() []string {
	names := make([]string, 0, len(colorSchemes))
	for name := range colorSchemes {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// fieldValue returns the human-readable string representation of a field's
// current value in the given config.
func fieldValue(f *configField, c *Config) string {
	switch f.Kind {
	case fieldBool:
		return strconv.FormatBool(f.getBool(*c))
	case fieldInt:
		return strconv.Itoa(f.getInt(*c))
	case fieldEnum:
		return f.getEnum(*c)
	default:
		return ""
	}
}

// indexOf returns the position of v in opts, or -1 if not found.
func indexOf(opts []string, v string) int {
	for i := range opts {
		if opts[i] == v {
			return i
		}
	}
	return -1
}

// truncateRight truncates s to fit within maxW display columns, appending
// an ellipsis ("...") when truncation is necessary.
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
