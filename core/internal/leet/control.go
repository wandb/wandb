package leet

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// ControlMsg is a request from wandb leet session to the running LEET,
// delivered to the Model through the channel in ModelParams.Control.
type ControlMsg struct {
	Method string
	Params json.RawMessage

	// Reply receives the reply. It is buffered.
	Reply chan<- ControlReply
}

// ControlReply is the result of a ControlMsg, or its error.
type ControlReply struct {
	Result any
	Err    *ControlError
}

// ControlError is a JSON-RPC 2.0 error.
type ControlError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// The JSON-RPC error codes of the control channel.
const (
	controlErrNoReply        = -32000
	controlErrBusy           = -32001
	controlErrInvalidRequest = -32600
	controlErrMethodNotFound = -32601
	controlErrInvalidParams  = -32602
	controlErrParse          = -32700
)

// controlLockName is the file in a wandb directory that says how to reach
// the LEET showing it.
const controlLockName = ".wandb-leet.lock"

// controlLock is the content of the lock file.
type controlLock struct {
	PID int `json:"pid"`

	// Address is "unix:<socket path>" or "tcp:127.0.0.1:<port>".
	Address string `json:"address"`

	// Token is the secret a TCP client sends first, or null on a socket.
	Token   *string `json:"token"`
	Started string  `json:"started"`
}

// ServeControl answers wandb leet session requests for the LEET showing
// wandbDir until ctx is done, then removes its socket and lock file.
//
// Each request goes to the Model receiving on control. The lock file is
// not written when another LEET holds a live lock on the directory or
// when wandbDir is not writable; LEET still serves its socket.
func ServeControl(
	ctx context.Context,
	wandbDir string,
	control chan<- ControlMsg,
	logger *observability.CoreLogger,
) {
	listener, address, token, err := listenControl()
	if err != nil {
		logger.Error(fmt.Sprintf("control: not listening: %v", err))
		return
	}

	lockPath := filepath.Join(wandbDir, controlLockName)
	lock := controlLock{
		PID:     os.Getpid(),
		Address: address,
		Started: time.Now().UTC().Format(time.RFC3339),
	}
	if token != "" {
		lock.Token = &token
	}
	writeControlLock(lockPath, lock, logger)

	go func() {
		<-ctx.Done()
		listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			break
		}
		go serveControlConn(conn, token, control)
	}

	if sock, ok := strings.CutPrefix(address, "unix:"); ok {
		_ = os.Remove(sock)
	}
	if cur, err := readControlLock(lockPath); err == nil && cur.PID == os.Getpid() {
		_ = os.Remove(lockPath)
	}
}

// listenControl listens on a Unix socket in a private directory next to
// the LEET config file, or on localhost with a token when it cannot.
func listenControl() (listener net.Listener, address, token string, err error) {
	dir := controlSocketDir()
	_ = os.MkdirAll(dir, 0o700)
	_ = os.Chmod(dir, 0o700)
	sock := filepath.Join(dir, fmt.Sprintf("leet-%d.sock", os.Getpid()))
	_ = os.Remove(sock)
	if listener, err = net.Listen("unix", sock); err == nil {
		_ = os.Chmod(sock, 0o600)
		return listener, "unix:" + sock, "", nil
	}

	if listener, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
		return nil, "", "", err
	}
	secret := make([]byte, 32)
	if _, err = rand.Read(secret); err != nil {
		listener.Close()
		return nil, "", "", err
	}
	return listener, "tcp:" + listener.Addr().String(), hex.EncodeToString(secret), nil
}

// controlSocketDir is the private directory next to the LEET config file
// that holds the control sockets.
func controlSocketDir() string {
	return filepath.Join(filepath.Dir(leetConfigPath()), "leet-sockets")
}

// writeControlLock claims path for this LEET unless another LEET holds it:
// one that answers a status request, or one whose process is still running.
func writeControlLock(path string, lock controlLock, logger *observability.CoreLogger) {
	if existing, err := readControlLock(path); err == nil {
		if controlLockLive(existing) ||
			(existing.PID > 0 && existing.PID != lock.PID && processExists(existing.PID)) {
			logger.Debug(fmt.Sprintf("control: %s is held by pid %d", path, existing.PID))
			return
		}
		if sock, ok := strings.CutPrefix(existing.Address, "unix:"); ok &&
			filepath.Dir(sock) == controlSocketDir() {
			if fi, err := os.Lstat(sock); err == nil && fi.Mode()&os.ModeSocket != 0 {
				_ = os.Remove(sock)
			}
		}
	}
	data, _ := json.Marshal(lock)
	f, err := os.CreateTemp(filepath.Dir(path), controlLockName+".*")
	if err == nil {
		_, err = f.Write(data)
		err = errors.Join(err, f.Close())
		if err == nil {
			err = os.Rename(f.Name(), path)
		}
		if err != nil {
			_ = os.Remove(f.Name())
		}
	}
	if err != nil {
		logger.Debug(fmt.Sprintf("control: not writing %s: %v", path, err))
	}
}

// processExists reports whether a process with pid is running.
func processExists(pid int) bool {
	p, err := os.FindProcess(pid)
	return err == nil && !errors.Is(p.Signal(syscall.Signal(0)), os.ErrProcessDone)
}

// controlLockLive reports whether the LEET a lock names answers a status
// request within 2 seconds.
func controlLockLive(lock controlLock) bool {
	conn, err := dialControl(lock, 2*time.Second)
	if err != nil {
		return false
	}
	defer conn.Close()
	_, err = controlRoundTrip(conn, `{"jsonrpc":"2.0","id":0,"method":"status"}`)
	return err == nil
}

// serveControlConn answers the requests of one connection, one at a time.
// A connection that sends nothing for 15 seconds is closed.
func serveControlConn(conn net.Conn, token string, control chan<- ControlMsg) {
	defer conn.Close()
	sc := bufio.NewScanner(conn)
	sc.Buffer(nil, 1<<20)
	_ = conn.SetReadDeadline(time.Now().Add(15 * time.Second))

	if token != "" {
		var hello struct {
			Token string `json:"token"`
		}
		if !sc.Scan() || json.Unmarshal(sc.Bytes(), &hello) != nil ||
			subtle.ConstantTimeCompare([]byte(hello.Token), []byte(token)) != 1 {
			return
		}
	}

	enc := json.NewEncoder(conn)
	for {
		_ = conn.SetReadDeadline(time.Now().Add(15 * time.Second))
		if !sc.Scan() {
			return
		}
		var req struct {
			ID     json.RawMessage `json:"id"`
			Method string          `json:"method"`
			Params json.RawMessage `json:"params"`
		}
		var reply ControlReply
		var typeErr *json.UnmarshalTypeError
		switch err := json.Unmarshal(sc.Bytes(), &req); {
		case errors.As(err, &typeErr):
			reply = controlError(controlErrInvalidRequest,
				"invalid request: expected a JSON-RPC object")
		case err != nil:
			reply = controlError(controlErrParse, "parse error: %v", err)
		case req.Method == "":
			reply = controlError(controlErrInvalidRequest, "invalid request: method is required")
		default:
			reply = requestControl(control, req.Method, req.Params)
		}

		resp := map[string]any{"jsonrpc": "2.0", "id": req.ID}
		if reply.Err != nil {
			resp["error"] = reply.Err
		} else {
			resp["result"] = reply.Result
		}
		if enc.Encode(resp) != nil {
			return
		}
	}
}

// requestControl sends a request to the Model and waits at most 10 seconds
// for its reply.
func requestControl(
	control chan<- ControlMsg,
	method string,
	params json.RawMessage,
) ControlReply {
	reply := make(chan ControlReply, 1)
	timeout := time.After(10 * time.Second)
	select {
	case control <- ControlMsg{Method: method, Params: params, Reply: reply}:
	case <-timeout:
		return controlError(controlErrNoReply, "no reply")
	}
	select {
	case r := <-reply:
		return r
	case <-timeout:
		return controlError(controlErrNoReply, "no reply")
	}
}

func controlError(code int, format string, args ...any) ControlReply {
	return ControlReply{Err: &ControlError{Code: code, Message: fmt.Sprintf(format, args...)}}
}

// decodeControlParams decodes a params object into p, a pointer to a
// struct, rejecting fields the method does not take.
func decodeControlParams(params json.RawMessage, p any) error {
	params = bytes.TrimSpace(params)
	if len(params) == 0 || bytes.Equal(params, []byte("null")) {
		return nil
	}
	if params[0] != '{' {
		return errors.New("params must be an object")
	}
	dec := json.NewDecoder(bytes.NewReader(params))
	dec.DisallowUnknownFields()
	err := dec.Decode(p)
	var typeErr *json.UnmarshalTypeError
	if errors.As(err, &typeErr) {
		return fmt.Errorf("%s has the wrong type", strings.TrimPrefix(typeErr.Field, "."))
	}
	return err
}

// waitForControl returns a command that delivers the next control request
// unless LEET restarts first, or nil when LEET has no control channel.
func (m *Model) waitForControl() tea.Cmd {
	if m.control == nil {
		return nil
	}
	return func() tea.Msg {
		select {
		case msg := <-m.control:
			return msg
		case <-m.restarting:
			return nil
		}
	}
}

// controlHandlers answer the control methods on the current view.
//
// Every method that changes the view returns the status object, so the
// caller sees the effect, plus its own fields.
var controlHandlers = map[string]func(*Model, json.RawMessage) (ControlReply, tea.Cmd){
	"status": func(m *Model, _ json.RawMessage) (ControlReply, tea.Cmd) {
		return ControlReply{Result: m.controlStatus()}, nil
	},
	"runs.select":   (*Model).controlSelectRuns,
	"runs.deselect": (*Model).controlDeselectRuns,
	"runs.pin":      (*Model).controlPinRun,
	"runs.open":     (*Model).controlOpenRun,
	"runs.close": func(m *Model, _ json.RawMessage) (ControlReply, tea.Cmd) {
		cmd := m.controlCloseRun()
		return ControlReply{Result: m.controlStatus()}, cmd
	},
	"filter.set":    (*Model).controlSetFilter,
	"metrics.focus": (*Model).controlFocusMetric,
	"step.goto":     (*Model).controlGotoStep,
	"action":        (*Model).controlAction,
	"actions": func(m *Model, _ json.RawMessage) (ControlReply, tea.Cmd) {
		return ControlReply{Result: map[string]any{"actions": m.controlActions()}}, nil
	},
}

// ControlMethods are the methods of the control channel.
var ControlMethods = slices.Sorted(maps.Keys(controlHandlers))

// handleControl answers a control request on the current view and returns
// the commands its changes need.
func (m *Model) handleControl(msg ControlMsg) (ControlReply, tea.Cmd) {
	if kind := m.pendingInput(); kind != "" && msg.Method != "status" {
		return controlError(controlErrBusy, "busy: LEET is waiting for user input (%s)", kind), nil
	}
	handle, ok := controlHandlers[msg.Method]
	if !ok {
		return controlError(controlErrMethodNotFound, "unknown method %q", msg.Method), nil
	}
	return handle(m, msg.Params)
}

// pendingInput names the input the user is in the middle of, or "".
func (m *Model) pendingInput() string {
	switch {
	case m.help.IsActive():
		return "help"
	case m.config.IsAwaitingGridConfig():
		return "grid_config"
	case m.mode == viewModeWorkspace && m.workspace.pendingSelectAll != nil:
		return "select_all"
	case m.isAwaitingUserInput():
		return "filter"
	}
	return ""
}

// controlRun returns the run of the run and inspect views, or nil in the
// workspace.
func (m *Model) controlRun() *Run {
	if m.mode == viewModeWorkspace {
		return nil
	}
	return m.run
}

func (m *Model) controlStatus() map[string]any {
	w := m.workspace
	mode := "workspace"
	metrics, system, focus := w.metricsGrid, w.systemMetricsFilter, w.focus
	if r := m.controlRun(); r != nil {
		mode = "run"
		if m.mode == viewModeInspect {
			mode = "inspect"
		}
		metrics, system, focus = r.metricsGrid, r.rightSidebar.metricsGrid.filter, r.focus
	}
	var focused any
	if focus.Type == FocusMainChart {
		focused = focus.Title
	}
	return map[string]any{
		"mode":                  mode,
		"wandb_dir":             localWandbDir(w.backend),
		"cursor_run":            orNil(w.SelectedRunKey()),
		"selected_runs":         append([]string{}, slices.Sorted(maps.Keys(w.selectedRuns))...),
		"pinned_run":            orNil(w.pinnedRun),
		"runs_filter":           controlFilterJSON(w.filter.Query(), w.filter.Mode()),
		"metrics_filter":        controlFilterJSON(metrics.FilterQuery(), metrics.FilterMode()),
		"system_metrics_filter": controlFilterJSON(system.Query(), system.Mode()),
		"focused_metric":        focused,
		"pending_input":         orNil(m.pendingInput()),
	}
}

func controlFilterJSON(query string, mode FilterMatchMode) map[string]any {
	return map[string]any{"query": query, "mode": mode.String()}
}

func (m *Model) controlSelectRuns(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Filter    string   `json:"filter"`
		Keys      []string `json:"keys"`
		Exclusive bool     `json:"exclusive"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	if p.Filter == "" && len(p.Keys) == 0 {
		return controlError(controlErrInvalidParams, "filter or keys required"), nil
	}
	w := m.workspace
	keys, err := w.controlRunKeys(p.Filter, p.Keys)
	if err != nil {
		return controlError(controlErrInvalidParams, "%v", err), nil
	}
	if len(keys) == 0 {
		return controlError(controlErrInvalidParams, "no run matches filter %q", p.Filter), nil
	}

	if p.Exclusive {
		for key := range w.selectedRuns {
			if !slices.Contains(keys, key) {
				w.dropRun(key)
			}
		}
	}
	var cmds []tea.Cmd
	unindexed := 0
	for _, key := range keys {
		if _, ok := w.runsFilterIndex[key]; !ok {
			unindexed++
		}
		if !w.selectedRuns[key] {
			cmds = append(cmds, w.selectRun(key))
		}
	}
	w.rememberRuns()

	result := m.controlStatus()
	result["unindexed"] = unindexed
	return ControlReply{Result: result}, batchCmds(cmds...)
}

func (m *Model) controlDeselectRuns(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Keys []string `json:"keys"`
		All  bool     `json:"all"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	if !p.All && len(p.Keys) == 0 {
		return controlError(controlErrInvalidParams, "keys or all required"), nil
	}
	w := m.workspace
	keys, err := w.controlRunKeys("", p.Keys)
	if err != nil {
		return controlError(controlErrInvalidParams, "%v", err), nil
	}
	if p.All {
		for key := range w.selectedRuns {
			if key != w.pinnedRun {
				w.dropRun(key)
			}
		}
	}
	for _, key := range keys {
		w.dropRun(key)
	}
	w.rememberRuns()
	return ControlReply{Result: m.controlStatus()}, nil
}

func (m *Model) controlPinRun(params json.RawMessage) (ControlReply, tea.Cmd) {
	w := m.workspace
	key, reply := w.controlRunKey(params)
	if reply.Err != nil {
		return reply, nil
	}
	var cmd tea.Cmd
	if !w.selectedRuns[key] {
		cmd = w.selectRun(key)
	}
	if w.pinnedRun != key {
		w.togglePin(key)
	} else if cmd != nil {
		w.rememberRuns()
	}
	return ControlReply{Result: m.controlStatus()}, cmd
}

// controlOpenRun opens the run view on a run, leaving the run view already
// open first.
func (m *Model) controlOpenRun(params json.RawMessage) (ControlReply, tea.Cmd) {
	w := m.workspace
	key, reply := w.controlRunKey(params)
	if reply.Err != nil {
		return reply, nil
	}
	visible := slices.ContainsFunc(w.runs.FilteredItems, func(it KeyValuePair) bool {
		return it.Key == key
	})
	if !visible {
		return controlError(controlErrInvalidParams,
			"run %q is not visible under the runs filter", key), nil
	}
	closeCmd := m.controlCloseRun()
	w.restoreRunCursor(key)
	openCmd := m.enterRunView()
	return ControlReply{Result: m.controlStatus()}, batchCmds(closeCmd, openCmd)
}

// controlCloseRun returns to the workspace from the run or inspect view.
func (m *Model) controlCloseRun() tea.Cmd {
	if m.mode == viewModeInspect {
		m.exitInspectView()
	}
	if m.mode == viewModeRun {
		return m.exitRunView()
	}
	return nil
}

// controlRunKey decodes {key} and resolves it to a run directory name.
func (w *Workspace) controlRunKey(params json.RawMessage) (string, ControlReply) {
	var p struct {
		Key string `json:"key"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return "", controlError(controlErrInvalidParams, "invalid params: %v", err)
	}
	keys, err := w.controlRunKeys("", []string{p.Key})
	if err != nil {
		return "", controlError(controlErrInvalidParams, "%v", err)
	}
	return keys[0], ControlReply{}
}

// controlRunKeys returns the run directory names a request names: the runs
// matching filter, in sidebar order, then those listed by directory name,
// ID or display name.
func (w *Workspace) controlRunKeys(filter string, keys []string) ([]string, error) {
	var out []string
	if filter != "" {
		compiled := CompileRunFilterQuery(filter, FilterModeRegex)
		for _, item := range w.runs.Items {
			if compiled.Match(w.runFilterData(item.Key)) {
				out = append(out, item.Key)
			}
		}
	}
	for _, key := range keys {
		var matches []string
		for _, item := range w.runs.Items {
			if item.Key == key || extractRunID(item.Key) == key ||
				w.runsFilterIndex[item.Key].DisplayName == key {
				matches = append(matches, item.Key)
			}
		}
		switch {
		case key == "" || len(matches) == 0:
			return nil, fmt.Errorf("unknown run %q", key)
		case len(matches) > 1:
			return nil, fmt.Errorf("%d runs are named %q: %s",
				len(matches), key, strings.Join(matches, ", "))
		}
		out = append(out, matches[0])
	}
	return out, nil
}

func (m *Model) controlSetFilter(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Target string `json:"target"`
		Query  string `json:"query"`
		Mode   string `json:"mode"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	var mode FilterMatchMode
	switch p.Mode {
	case "":
	case "regex":
		mode = FilterModeRegex
	case "glob":
		mode = FilterModeGlob
	default:
		return controlError(controlErrInvalidParams, "mode must be regex or glob"), nil
	}

	w, r := m.workspace, m.controlRun()
	if r != nil {
		r.stateMu.Lock()
		defer r.stateMu.Unlock()
	}
	switch {
	case p.Target == "runs":
		w.filter.Set(p.Query, mode)
		w.applyRunFilter()
	case p.Target == "metrics" && r != nil:
		r.metricsGrid.SetFilter(p.Query, mode)
	case p.Target == "metrics":
		w.metricsGrid.SetFilter(p.Query, mode)
	case p.Target == "system" && r != nil:
		r.rightSidebar.metricsGrid.filter.Set(p.Query, mode)
		r.rightSidebar.metricsGrid.ApplyFilter()
	case p.Target == "system":
		w.systemMetricsFilter.Set(p.Query, mode)
		w.activeSystemMetricsGrid().ApplyFilter()
	default:
		return controlError(controlErrInvalidParams, "target must be runs, metrics or system"), nil
	}
	return ControlReply{Result: m.controlStatus()}, nil
}

func (m *Model) controlFocusMetric(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Key string `json:"key"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	w, r := m.workspace, m.controlRun()
	mg := w.metricsGrid
	if r != nil {
		r.stateMu.Lock()
		defer r.stateMu.Unlock()
		mg = r.metricsGrid
	}
	if !mg.FocusChartByTitle(p.Key) {
		return controlError(controlErrInvalidParams,
			"metric %q is not visible under the current filter", p.Key), nil
	}
	if r != nil {
		r.adoptChartMouseFocus()
	} else {
		w.adoptChartMouseFocus()
	}
	return ControlReply{Result: m.controlStatus()}, nil
}

// controlGotoStep puts the crosshair of the step-axis charts at a step and,
// in the run view, selects the console line logged nearest to it.
func (m *Model) controlGotoStep(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Step *float64 `json:"step"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	if p.Step == nil {
		return controlError(controlErrInvalidParams, "step required"), nil
	}
	if r := m.controlRun(); r != nil {
		r.stateMu.Lock()
		defer r.stateMu.Unlock()
		r.metricsGrid.broadcastInspectAtDataX(*p.Step, "")
		if t, ok := r.stepTimes.timeAt(*p.Step); ok {
			r.rightSidebar.metricsGrid.broadcastInspectAtDataX(float64(t.UnixNano()) / 1e9)
			r.consoleLogsPane.SelectIndex(r.consoleLogs.IndexNear(t))
		}
	} else {
		m.workspace.metricsGrid.broadcastInspectAtDataX(*p.Step, "")
	}
	result := m.controlStatus()
	result["step"] = *p.Step
	return ControlReply{Result: result}, nil
}

// controlAction presses a key binding of the current view named by its
// feature name, as the help screen lists them: the given key of the
// binding, or its first key. The binding acts on the focused pane, as the
// key would. A binding that starts a filter or a prompt is undone, as Esc
// would, and rejected.
func (m *Model) controlAction(params json.RawMessage) (ControlReply, tea.Cmd) {
	var p struct {
		Name string `json:"name"`
		Key  string `json:"key"`
	}
	if err := decodeControlParams(params, &p); err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	var cmd tea.Cmd
	var ok bool
	switch m.mode {
	case viewModeWorkspace:
		cmd, ok = runControlAction(m.workspace, WorkspaceKeyBindings(), p.Name, p.Key)
	case viewModeRun:
		m.run.stateMu.Lock()
		cmd, ok = runControlAction(m.run, RunKeyBindings(), p.Name, p.Key)
		m.run.syncChartsToConsole()
		m.run.stateMu.Unlock()
	case viewModeInspect:
		cmd, ok = runControlAction(m.inspector, InspectorKeyBindings(), p.Name, p.Key)
	}
	switch {
	case !ok && p.Key != "":
		return controlError(controlErrInvalidParams,
			"no action %q bound to key %q", p.Name, p.Key), nil
	case !ok:
		return controlError(controlErrInvalidParams, "unknown action %q", p.Name), nil
	case m.pendingInput() != "":
		cmds := m.updateSubComponents(tea.KeyPressMsg{Code: tea.KeyEsc})
		reply := controlError(controlErrInvalidParams,
			"action %q enters an input mode; use filter.set or runs.select", p.Name)
		return reply, tea.Batch(cmds...)
	}
	result := m.controlStatus()
	result["action"] = p.Name
	return ControlReply{Result: result}, cmd
}

// controlActions lists the key bindings of the current view.
func (m *Model) controlActions() []any {
	switch m.mode {
	case viewModeRun:
		return listControlActions(RunKeyBindings())
	case viewModeInspect:
		return listControlActions(InspectorKeyBindings())
	}
	return listControlActions(WorkspaceKeyBindings())
}

// runControlAction presses key, or the first key when key is empty, of a
// binding named name. Quit is not an action.
func runControlAction[T any](
	t *T,
	categories []BindingCategory[T],
	name, key string,
) (tea.Cmd, bool) {
	if strings.HasSuffix(name, ".quit") {
		return nil, false
	}
	for _, category := range categories {
		for _, b := range category.Bindings {
			if b.Handler == nil || featureName(b.Handler) != name {
				continue
			}
			if key == "" {
				key = b.Keys[0]
			}
			if slices.Contains(b.Keys, key) {
				return b.Handler(t, keyPressFor(key)), true
			}
		}
	}
	return nil, false
}

func listControlActions[T any](categories []BindingCategory[T]) []any {
	actions := []any{}
	for _, category := range categories {
		for _, b := range category.Bindings {
			if b.Handler == nil {
				continue
			}
			name := featureName(b.Handler)
			if strings.HasSuffix(name, ".quit") {
				continue
			}
			actions = append(actions, map[string]any{
				"name":        name,
				"keys":        b.Keys,
				"description": b.Description,
			})
		}
	}
	return actions
}

// keyPressFor builds a key press whose String is key.
func keyPressFor(key string) tea.KeyPressMsg {
	if r, size := utf8.DecodeRuneInString(key); size == len(key) {
		return tea.KeyPressMsg{Code: r, Text: key}
	}
	return tea.KeyPressMsg{Code: tea.KeyExtended, Text: key}
}
