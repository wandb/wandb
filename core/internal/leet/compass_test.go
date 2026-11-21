package leet_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// A node's children come from a call on the scope narrowed to the node, and
// a team whose runs sent no samples is unavailable, not zero.
func TestCompass_NodeSelectNarrowsScope(t *testing.T) {
	t.Setenv("WANDB_API_KEY", "compass-test-key")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Scope   struct{ Team, User string }
			GroupBy []string `json:"group_by"`
		}
		require.NoError(t, json.NewDecoder(r.Body).Decode(&req))
		rows := `{"gpu_hours":30,"runs":5}`
		switch strings.Join(req.GroupBy, ",") + "|" + req.Scope.Team + "|" + req.Scope.User {
		case "GROUP_BY_TEAM||":
			rows = `{"group":{"team":"team-a"},"gpu_hours":30,"gpu_utilization_ratio":0.5,"runs":3},
				{"group":{"team":"team-b"},"runs":2}`
		case "GROUP_BY_TEAM,GROUP_BY_USER|team-a|":
			rows = `{"group":{"team":"team-a","user":"u1"},"gpu_hours":20,"runs":2},
				{"group":{"team":"team-a","user":"u2"},"gpu_hours":10,"runs":1}`
		case "GROUP_BY_TEAM,GROUP_BY_USER,GROUP_BY_PROJECT|team-a|u1":
			rows = `{"group":{"team":"team-a","user":"u1","project":"team-a/p1"},"gpu_hours":20,"runs":2}`
		}
		_, _ = w.Write([]byte(`{"rows":[` + rows + `]}`))
	}))
	defer server.Close()

	c, err := leet.NewCompass(&leet.RemoteRunParams{BaseURL: server.URL, Org: "org"}, nil)
	require.NoError(t, err)
	pump := func(cmd tea.Cmd) {
		for queue := []tea.Cmd{cmd}; len(queue) > 0; queue = queue[1:] {
			if queue[0] == nil {
				continue
			}
			msg := queue[0]()
			if batch, ok := msg.(tea.BatchMsg); ok {
				queue = append(queue, batch...)
				continue
			}
			_, next := c.Update(msg)
			queue = append(queue, next)
		}
	}
	control := func(method, params string) map[string]any {
		reply := make(chan leet.ControlReply, 1)
		_, cmd := c.Update(leet.ControlMsg{
			Method: method, Params: json.RawMessage(params), Reply: reply,
		})
		pump(cmd)
		got := <-reply
		require.Nil(t, got.Err)
		return got.Result.(map[string]any)
	}

	pump(c.Init())
	c.Update(tea.WindowSizeMsg{Width: 160, Height: 40})
	control("node.select", `{"path":["team-a","u1"]}`)

	selected := control("status", "")["selected"].(map[string]any)
	require.Equal(t, []string{"team-a", "u1"}, selected["path"])
	require.Equal(t, []string{"team-a/p1"}, selected["children"])
	view := stripANSI(c.View().Content)
	for line := range strings.SplitSeq(view, "\n") {
		if strings.Contains(line, "team-b") {
			require.Contains(t, line, "n/a")
			return
		}
	}
	t.Fatalf("team-b is not in the view:\n%s", view)
}
