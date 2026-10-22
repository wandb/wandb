package leet_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

const (
	controlRunA = "run-20250731_170601-aaaaaaaa"
	controlRunB = "run-20250731_170602-bbbbbbbb"
	controlRunC = "run-20250731_170603-cccccccc"
)

// newControlModel opens a workspace on wandbDir with three runs, two of
// them with a preloaded Run record. The newest, controlRunC, is selected.
func newControlModel(t *testing.T, wandbDir string) *leet.Model {
	t.Helper()
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	m := leet.NewModel(leet.ModelParams{
		Backend: leet.NewLocalWorkspaceBackend(wandbDir, logger),
		Config:  cfg,
		Logger:  logger,
	})
	m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m.Update(leet.WorkspaceRunDiscoveryMsg{
		RunKeys: []string{controlRunC, controlRunB, controlRunA}})
	m.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: controlRunA, Run: &leet.RunMsg{ID: "aaaaaaaa", DisplayName: "resnet-a"}})
	m.Update(leet.WorkspaceRunOverviewPreloadedMsg{
		RunKey: controlRunB, Run: &leet.RunMsg{ID: "bbbbbbbb", DisplayName: "vit-b"}})
	return m
}

// control sends one request to the model and returns its reply and the
// command the model issued for it.
func control(m *leet.Model, method, params string) (leet.ControlReply, tea.Cmd) {
	reply := make(chan leet.ControlReply, 1)
	_, cmd := m.Update(
		leet.ControlMsg{Method: method, Params: json.RawMessage(params), Reply: reply})
	return <-reply, cmd
}

func readDirState(t *testing.T, wandbDir string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(wandbDir, ".wandb-leet.json"))
	require.NoError(t, err)
	var state map[string]any
	require.NoError(t, json.Unmarshal(data, &state))
	return state
}

func TestControl_SelectRunsByFilter(t *testing.T) {
	wandbDir := t.TempDir()
	m := newControlModel(t, wandbDir)

	reply, cmd := control(m, "runs.select", `{"filter": "name:resnet", "exclusive": true}`)
	require.Nil(t, reply.Err)
	require.NotNil(t, cmd)
	result := reply.Result.(map[string]any)
	require.Equal(t, []string{controlRunA}, result["selected_runs"])
	require.Equal(t, 0, result["unindexed"])

	reply, _ = control(m, "runs.select", `{"keys": ["cccccccc"]}`)
	require.Nil(t, reply.Err)
	result = reply.Result.(map[string]any)
	require.Equal(t, []string{controlRunA, controlRunC}, result["selected_runs"])
	require.Equal(t, 1, result["unindexed"])

	require.Equal(t,
		[]any{controlRunA, controlRunC}, readDirState(t, wandbDir)["selected_runs"])

	reply, _ = control(m, "runs.deselect", `{"keys": ["aaaaaaaa", "cccccccc"]}`)
	require.Nil(t, reply.Err)
	require.Equal(t, []string{}, reply.Result.(map[string]any)["selected_runs"])
}

func TestControl_SetRunsFilter(t *testing.T) {
	wandbDir := t.TempDir()
	m := newControlModel(t, wandbDir)

	reply, _ := control(m, "filter.set", `{"target": "runs", "query": "name:vit"}`)
	require.Nil(t, reply.Err)
	require.Equal(t, []string{controlRunB}, m.TestWorkspace().TestFilteredRunKeys())

	filter := readDirState(t, wandbDir)["runs_filter"].(map[string]any)
	require.Equal(t, "name:vit", filter["query"])

	status, _ := control(m, "status", "")
	require.Equal(t,
		"name:vit", status.Result.(map[string]any)["runs_filter"].(map[string]any)["query"])
}

func TestControl_BusyWhileTypingAFilter(t *testing.T) {
	m := newControlModel(t, t.TempDir())
	m.Update(tea.KeyPressMsg{Code: 'f', Text: "f"})

	reply, _ := control(m, "runs.select", `{"filter": "name:resnet"}`)
	require.NotNil(t, reply.Err)
	require.Equal(t, -32001, reply.Err.Code)
	require.Contains(t, reply.Err.Message, "filter")

	reply, _ = control(m, "status", "")
	require.Nil(t, reply.Err)
	require.Equal(t, "filter", reply.Result.(map[string]any)["pending_input"])
}

func TestControl_ActionCannotEnterAnInputMode(t *testing.T) {
	m := newControlModel(t, t.TempDir())

	reply, _ := control(m, "action", `{"name": "workspace.enter_runs_filter"}`)
	require.NotNil(t, reply.Err)
	require.Equal(t, -32602, reply.Err.Code)

	reply, _ = control(m, "status", "")
	require.Nil(t, reply.Result.(map[string]any)["pending_input"])
}

func TestControl_ActionPressesTheGivenKey(t *testing.T) {
	m := newControlModel(t, t.TempDir())
	require.Equal(t, controlRunC, m.TestWorkspace().SelectedRunKey())

	reply, _ := control(m, "action", `{"name": "workspace.runs_vertical_nav", "key": "s"}`)
	require.Nil(t, reply.Err)
	require.Equal(t, controlRunB, reply.Result.(map[string]any)["cursor_run"])
}

func TestControl_ActionsIsAnObject(t *testing.T) {
	m := newControlModel(t, t.TempDir())

	reply, _ := control(m, "actions", "{}")
	require.Nil(t, reply.Err)
	require.NotEmpty(t, reply.Result.(map[string]any)["actions"])
}

func TestControl_RestartStopsWaiting(t *testing.T) {
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(leet.ModelParams{
		Backend: leet.NewLocalWorkspaceBackend(t.TempDir(), logger),
		Control: make(chan leet.ControlMsg),
		Config:  leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger),
		Logger:  logger,
	})
	wait := m.TestWaitForControl()

	m.Update(tea.KeyPressMsg{Code: 'r', Mod: tea.ModAlt})
	require.Nil(t, wait())
}

// serveControl runs ServeControl with a channel whose requests a goroutine
// answers with {"ok": true}, and returns a function that stops it and
// waits for its cleanup.
func serveControl(t *testing.T, wandbDir string) (stop func()) {
	t.Helper()
	t.Setenv("WANDB_CONFIG_DIR", t.TempDir())

	ctrl := make(chan leet.ControlMsg)
	go func() {
		for msg := range ctrl {
			msg.Reply <- leet.ControlReply{Result: map[string]any{"ok": true}}
		}
	}()

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		leet.ServeControl(ctx, wandbDir, ctrl, observability.NewNoOpLogger())
	}()
	return func() {
		cancel()
		<-done
		close(ctrl)
	}
}

// waitForLock polls the lock file of wandbDir until it names pid.
func waitForLock(t *testing.T, wandbDir string, pid int) map[string]any {
	t.Helper()
	path := filepath.Join(wandbDir, ".wandb-leet.lock")
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		var lock map[string]any
		if data, err := os.ReadFile(path); err == nil &&
			json.Unmarshal(data, &lock) == nil && lock["pid"] == float64(pid) {
			return lock
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("no lock for pid %d in %s", pid, wandbDir)
	return nil
}

func TestServeControl_AnswersAndCleansUp(t *testing.T) {
	wandbDir := t.TempDir()
	stale := staleLock(t, math.MaxInt32)
	require.NoError(t,
		os.WriteFile(filepath.Join(wandbDir, ".wandb-leet.lock"), []byte(stale), 0o600))

	stop := serveControl(t, wandbDir)
	lock := waitForLock(t, wandbDir, os.Getpid())

	var out bytes.Buffer
	err := leet.SessionRequest(wandbDir, `{"jsonrpc":"2.0","id":7,"method":"status"}`, &out)
	require.NoError(t, err)
	require.JSONEq(t, `{"jsonrpc":"2.0","id":7,"result":{"ok":true}}`, out.String())

	stop()
	_, err = os.Stat(filepath.Join(wandbDir, ".wandb-leet.lock"))
	require.ErrorIs(t, err, os.ErrNotExist)
	if sock, ok := strings.CutPrefix(lock["address"].(string), "unix:"); ok {
		_, err = os.Stat(sock)
		require.ErrorIs(t, err, os.ErrNotExist)
	}

	err = leet.SessionRequest(wandbDir, `{"jsonrpc":"2.0","id":8,"method":"status"}`, &out)
	require.ErrorContains(t, err, "no LEET is showing")
}

// staleLock is a lock file naming pid and a socket that does not exist.
func staleLock(t *testing.T, pid int) string {
	t.Helper()
	return fmt.Sprintf(
		`{"pid": %d, "address": "unix:%s", "token": null, "started": "2026-01-01T00:00:00Z"}`,
		pid, filepath.Join(t.TempDir(), "gone.sock"))
}

func TestServeControl_LeavesALiveLockAlone(t *testing.T) {
	wandbDir := t.TempDir()
	lockPath := filepath.Join(wandbDir, ".wandb-leet.lock")
	stop := serveControl(t, wandbDir)
	defer stop()
	lock := waitForLock(t, wandbDir, os.Getpid())

	lock["pid"] = float64(os.Getpid() + 1)
	data, err := json.Marshal(lock)
	require.NoError(t, err)
	require.NoError(t, os.WriteFile(lockPath, data, 0o600))

	stop2 := serveControl(t, wandbDir)
	stop2()
	got, err := os.ReadFile(lockPath)
	require.NoError(t, err)
	require.JSONEq(t, string(data), string(got))
}

func TestServeControl_LeavesTheLockOfALiveProcessAlone(t *testing.T) {
	wandbDir := t.TempDir()
	lockPath := filepath.Join(wandbDir, ".wandb-leet.lock")
	stale := staleLock(t, os.Getppid())
	require.NoError(t, os.WriteFile(lockPath, []byte(stale), 0o600))

	stop := serveControl(t, wandbDir)
	stop()
	got, err := os.ReadFile(lockPath)
	require.NoError(t, err)
	require.JSONEq(t, stale, string(got))
}
