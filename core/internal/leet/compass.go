package leet

import (
	"cmp"
	"encoding/json"
	"fmt"
	"maps"
	"slices"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"

	computev1 "github.com/wandb/wandb/core/internal/leet/computeproto"
)

// compassTopRuns is how many runs of a node the Teams tree lists. The
// Compute API returns every run of a group, unordered.
const compassTopRuns = 20

// compassOrders are the hierarchies the o key cycles through.
var compassOrders = [][]string{
	{"team", "user", "project", "run"},
	{"team", "project", "user", "run"},
	{"project", "user", "run"},
	{"user", "project", "run"},
}

var compassTabs = []string{"overview", "teams"}

// Compass is the Compute Compass view: the compute usage of a W&B
// organization or team from the Compute API, as an Overview and a Teams
// hierarchy.
//
// Implements tea.Model.
type Compass struct {
	// params is the scope LEET was opened on.
	params  *RemoteRunParams
	clients *remoteClients
	control <-chan ControlMsg

	width, height int

	tab    string
	team   string
	models []string
	tags   []string

	// period is week, month or a period of wandb leet compute usage.
	period string

	// order lists the group-by keys of the Teams levels, outermost first.
	order []string

	// gen counts refreshes; replies to an earlier one are dropped.
	gen     int
	pending int
	err     error

	// resolved and asOf are the period and the data-through time the
	// server reported for the scope.
	resolved *computev1.Period
	asOf     time.Time
	total    *computev1.UsageRow
	projects []*computev1.UsageRow
	users    []*computev1.UsageRow

	// teamOptions and modelOptions are what the t and d keys cycle through.
	teamOptions, modelOptions []string

	root     *compassNode
	selected *compassNode

	// want is the path node.select is still loading its way down.
	want []string
}

// compassNode is a row of the Teams tree.
type compassNode struct {
	// level is the node's group-by key, or "" for the root.
	level string
	key   string

	// row comes from the call that listed the node, never from its children.
	row *computev1.UsageRow

	parent   *compassNode
	children []*compassNode

	// more and moreHours describe the runs below the top compassTopRuns.
	more      int
	moreHours float64

	expanded, loaded, loading bool
}

type compassUsageMsg struct {
	gen  int
	dest string
	node *compassNode
	resp *computev1.ComputeUsageResponse
	err  error
}

// NewCompass returns the Compute Compass view of the organization, team or
// project params names. Control delivers wandb leet session requests, or
// is nil.
func NewCompass(params *RemoteRunParams, control <-chan ControlMsg) (*Compass, error) {
	clients, err := newComputeClients(params.BaseURL)
	if err != nil {
		return nil, err
	}
	root := &compassNode{expanded: true}
	return &Compass{
		params:   params,
		clients:  clients,
		control:  control,
		tab:      "overview",
		period:   "month",
		order:    compassOrders[0],
		root:     root,
		selected: root,
	}, nil
}

func (c *Compass) Init() tea.Cmd {
	return tea.Batch(tea.RequestBackgroundColor, c.waitForControl(), c.refresh())
}

func (c *Compass) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		c.width, c.height = msg.Width, msg.Height
	case tea.BackgroundColorMsg:
		SetDarkBackground(msg.IsDark())
		SetTerminalBackground(msg)
	case ControlMsg:
		reply, change := c.handleControl(msg)
		msg.Reply <- reply
		cmd = tea.Batch(change, c.waitForControl())
	case compassUsageMsg:
		cmd = c.handleUsage(msg)
	case tea.KeyPressMsg:
		cmd = c.handleKey(msg)
	}
	return c, cmd
}

func (c *Compass) waitForControl() tea.Cmd {
	if c.control == nil {
		return nil
	}
	return func() tea.Msg { return <-c.control }
}

func (c *Compass) handleKey(msg tea.KeyPressMsg) tea.Cmd {
	nodes, node := c.visible(), c.selected
	at := slices.Index(nodes, node)
	switch msg.String() {
	case "q", "ctrl+c":
		return tea.Quit
	case "tab":
		c.tab = compassTabs[(slices.Index(compassTabs, c.tab)+1)%len(compassTabs)]
	case "w":
		c.period = "week"
		return c.refresh()
	case "m":
		c.period = "month"
		return c.refresh()
	case "r":
		return c.refresh()
	case "t":
		if c.params.Entity == "" {
			c.team = compassNext(c.teamOptions, c.team)
			return c.refresh()
		}
	case "d":
		next := compassNext(c.modelOptions, strings.Join(c.models, ","))
		c.models = nil
		if next != "" {
			c.models = []string{next}
		}
		return c.refresh()
	case "o":
		i := slices.IndexFunc(compassOrders, func(o []string) bool {
			return slices.Equal(o, c.order)
		})
		c.order = compassOrders[(i+1)%len(compassOrders)]
		return c.resetTree()
	case "up", "k":
		c.selected = nodes[max(at-1, 0)]
	case "down", "j":
		c.selected = nodes[min(at+1, len(nodes)-1)]
	case "right", "l", "enter":
		node.expanded = true
		return c.loadChildren(node)
	case "left", "h":
		if node.expanded && node.parent != nil {
			node.expanded = false
		} else if node.parent != nil {
			c.selected = node.parent
		}
	}
	return nil
}

// compassNext returns the option after current, or "" after the last one.
func compassNext(options []string, current string) string {
	if i := slices.Index(options, current) + 1; i < len(options) {
		return options[i]
	}
	return ""
}

// compassPeriod resolves week, month or a period of wandb leet compute
// usage to whole UTC days.
func compassPeriod(period string) (*computev1.Period, error) {
	switch period {
	case "week":
		period = "7d"
	case "month":
		period = "30d"
	}
	resolved, _, err := computePeriods(period, time.Now().UTC())
	return resolved, err
}

// request builds the usage request of the scope narrowed to node.
func (c *Compass) request(node *compassNode, groups ...string) *computev1.ComputeUsageRequest {
	scope := &computev1.Scope{
		Org:     c.params.Org,
		Team:    cmp.Or(c.params.Entity, c.team),
		Project: c.params.Project,
		Tags:    c.tags,
	}
	for n := node; n != nil; n = n.parent {
		switch n.level {
		case "team":
			scope.Team = n.key
		case "user":
			scope.User = n.key
		case "project":
			scope.Team, scope.Project, _ = strings.Cut(n.key, "/")
		}
	}
	req := &computev1.ComputeUsageRequest{
		Scope:  scope,
		Period: c.resolved,
		Basis:  computev1.Basis_BASIS_PHYSICAL,
	}
	if len(c.models) > 0 {
		req.Filters = &computev1.Filters{DeviceModels: c.models}
	}
	for _, group := range groups {
		req.GroupBy = append(req.GroupBy,
			computev1.GroupBy(computev1.GroupBy_value["GROUP_BY_"+strings.ToUpper(group)]))
	}
	return req
}

func (c *Compass) call(
	dest string,
	node *compassNode,
	req *computev1.ComputeUsageRequest,
) tea.Cmd {
	c.pending++
	gen := c.gen
	return func() tea.Msg {
		resp := &computev1.ComputeUsageResponse{}
		err := c.clients.computeCall(c.params.BaseURL, "ComputeUsage", req, resp)
		return compassUsageMsg{gen: gen, dest: dest, node: node, resp: resp, err: err}
	}
}

// refresh drops what is shown and reads the scope again.
func (c *Compass) refresh() tea.Cmd {
	c.gen++
	c.pending, c.err = 0, nil
	c.total, c.projects, c.users, c.asOf = nil, nil, nil, time.Time{}
	c.resolved, c.err = compassPeriod(c.period)
	if c.err != nil {
		return nil
	}
	// The options are the teams and device models of the unfiltered scope.
	options := c.request(nil, "team")
	options.Scope.Team, options.Filters = c.params.Entity, nil
	return tea.Batch(
		c.call("total", nil, c.request(nil)),
		c.call("projects", nil, c.request(nil, "project")),
		c.call("users", nil, c.request(nil, "user")),
		c.call("options", nil, options),
		c.resetTree(),
	)
}

// resetTree collapses the Teams tree to its root and loads the first level.
func (c *Compass) resetTree() tea.Cmd {
	c.root = &compassNode{row: c.total, expanded: true}
	c.selected, c.want = c.root, nil
	return c.loadChildren(c.root)
}

// loadChildren reads the next level under node: the scope narrowed to
// node, grouped by the levels down to its children.
func (c *Compass) loadChildren(node *compassNode) tea.Cmd {
	depth := node.depth()
	if node.loaded || node.loading || depth == len(c.order) {
		return nil
	}
	node.loading = true
	return c.call("children", node, c.request(node, c.order[:depth+1]...))
}

func (n *compassNode) depth() int {
	if n.parent == nil {
		return 0
	}
	return n.parent.depth() + 1
}

func (n *compassNode) top() *compassNode {
	if n.parent == nil {
		return n
	}
	return n.parent.top()
}

func (n *compassNode) path() []string {
	if n.parent == nil {
		return []string{}
	}
	return append(n.parent.path(), n.key)
}

func (c *Compass) handleUsage(msg compassUsageMsg) tea.Cmd {
	if msg.gen != c.gen {
		return nil
	}
	c.pending--
	if msg.node != nil {
		msg.node.loading = false
	}
	if msg.err != nil {
		c.err = msg.err
		return nil
	}
	rows := msg.resp.GetRows()
	switch msg.dest {
	case "total":
		if len(rows) > 0 {
			c.total, c.root.row = rows[0], rows[0]
		}
		if at := msg.resp.GetAsOf(); at != nil {
			c.asOf = at.AsTime()
		}
	case "projects":
		c.projects = compassRanked(rows, "project")
	case "users":
		c.users = compassRanked(rows, "user")
	case "options":
		c.teamOptions, c.modelOptions = nil, nil
		for _, row := range rows {
			c.teamOptions = append(c.teamOptions, row.GetGroup()["team"])
			c.modelOptions = slices.AppendSeq(c.modelOptions, maps.Keys(row.GetHardware()))
		}
		slices.Sort(c.teamOptions)
		slices.Sort(c.modelOptions)
		c.modelOptions = slices.Compact(c.modelOptions)
	case "children":
		// A reply for a tree that was rebuilt since the call is dropped.
		if msg.node.top() == c.root {
			c.setChildren(msg.node, rows)
			return c.seek()
		}
	}
	return nil
}

// compassRanked sorts rows by GPU-hours, largest first.
func compassRanked(rows []*computev1.UsageRow, key string) []*computev1.UsageRow {
	slices.SortFunc(rows, func(a, b *computev1.UsageRow) int {
		return cmp.Or(
			cmp.Compare(b.GetGpuHours(), a.GetGpuHours()),
			cmp.Compare(a.GetGroup()[key], b.GetGroup()[key]),
		)
	})
	return rows
}

// setChildren hangs the rows of the next level under node, keeping the top
// compassTopRuns of a run level.
func (c *Compass) setChildren(node *compassNode, rows []*computev1.UsageRow) {
	level := c.order[node.depth()]
	rows = compassRanked(rows, level)
	if level == "run" && len(rows) > compassTopRuns {
		node.more = len(rows) - compassTopRuns
		for _, row := range rows[compassTopRuns:] {
			node.moreHours += row.GetGpuHours()
		}
		rows = rows[:compassTopRuns]
	}
	for _, row := range rows {
		node.children = append(node.children,
			&compassNode{level: level, key: row.GetGroup()[level], row: row, parent: node})
	}
	node.loaded = true
}

// visible lists the rows of the Teams tree, top to bottom.
func (c *Compass) visible() []*compassNode {
	var nodes []*compassNode
	var walk func(n *compassNode)
	walk = func(n *compassNode) {
		nodes = append(nodes, n)
		if n.expanded {
			for _, child := range n.children {
				walk(child)
			}
		}
	}
	walk(c.root)
	return nodes
}

// label is a node's key without the team and project its ancestors name.
func (c *Compass) label(n *compassNode) string {
	if n.parent == nil {
		return cmp.Or(c.params.Entity, c.team, "All teams")
	}
	scope := c.request(n.parent).Scope
	label := strings.TrimPrefix(n.key, scope.Team+"/")
	return cmp.Or(strings.TrimPrefix(label, scope.Project+"/"), "(none)")
}

// seek selects and unfolds the node at the path of node.select, loading
// the levels it has not read yet. It runs again when they arrive.
func (c *Compass) seek() tea.Cmd {
	if c.want == nil {
		return nil
	}
	node := c.root
	for _, name := range c.want {
		node.expanded = true
		if !node.loaded {
			return c.loadChildren(node)
		}
		i := slices.IndexFunc(node.children, func(child *compassNode) bool {
			return child.key == name || c.label(child) == name
		})
		if i < 0 {
			c.err = fmt.Errorf("node.select: no %q under %s", name, c.label(node))
			break
		}
		node = node.children[i]
	}
	c.want, c.selected, node.expanded = nil, node, true
	return c.loadChildren(node)
}

// compassControlHandlers answer the control methods of the Compute Compass
// view. Each returns the status object.
var compassControlHandlers = map[string]func(*Compass, json.RawMessage) (tea.Cmd, error){
	"status": func(*Compass, json.RawMessage) (tea.Cmd, error) { return nil, nil },
	"tab.set": func(c *Compass, params json.RawMessage) (tea.Cmd, error) {
		var p struct {
			Tab string `json:"tab"`
		}
		if err := decodeControlParams(params, &p); err != nil {
			return nil, err
		}
		if !slices.Contains(compassTabs, p.Tab) {
			return nil, fmt.Errorf("tab must be overview or teams")
		}
		c.tab = p.Tab
		return nil, nil
	},
	"scope.set": func(c *Compass, params json.RawMessage) (tea.Cmd, error) {
		var p struct {
			Team         *string   `json:"team"`
			DeviceModels *[]string `json:"device_models"`
			Tags         *[]string `json:"tags"`
		}
		if err := decodeControlParams(params, &p); err != nil {
			return nil, err
		}
		if p.Team != nil && c.params.Entity != "" {
			return nil, fmt.Errorf("the view is open on team %q", c.params.Entity)
		}
		if p.Team != nil {
			c.team = *p.Team
		}
		if p.DeviceModels != nil {
			c.models = *p.DeviceModels
		}
		if p.Tags != nil {
			c.tags = *p.Tags
		}
		return c.refresh(), nil
	},
	"period.set": func(c *Compass, params json.RawMessage) (tea.Cmd, error) {
		var p struct {
			Period string `json:"period"`
		}
		if err := decodeControlParams(params, &p); err != nil {
			return nil, err
		}
		if _, err := compassPeriod(p.Period); err != nil {
			return nil, fmt.Errorf("period must be week, month, YYYY-MM," +
				" YYYY-MM-DD:YYYY-MM-DD or a positive Nd")
		}
		c.period = p.Period
		return c.refresh(), nil
	},
	"hierarchy.set": func(c *Compass, params json.RawMessage) (tea.Cmd, error) {
		var p struct {
			Order []string `json:"order"`
		}
		if err := decodeControlParams(params, &p); err != nil {
			return nil, err
		}
		for i, level := range p.Order {
			if !slices.Contains(compassOrders[0], level) || slices.Contains(p.Order[:i], level) ||
				(level == "run" && i < len(p.Order)-1) {
				return nil, fmt.Errorf(
					"order must list team, user and project once each at most, then run or nothing")
			}
		}
		if len(p.Order) == 0 {
			return nil, fmt.Errorf("order required")
		}
		c.order = p.Order
		return c.resetTree(), nil
	},
	"node.select": func(c *Compass, params json.RawMessage) (tea.Cmd, error) {
		var p struct {
			Path []string `json:"path"`
		}
		if err := decodeControlParams(params, &p); err != nil {
			return nil, err
		}
		c.tab, c.err = "teams", nil
		c.want = append([]string{}, p.Path...)
		return c.seek(), nil
	},
}

func (c *Compass) handleControl(msg ControlMsg) (ControlReply, tea.Cmd) {
	handle, ok := compassControlHandlers[msg.Method]
	if !ok {
		return controlError(controlErrMethodNotFound,
			"unknown method %q: the Compute Compass view takes %s", msg.Method,
			strings.Join(slices.Sorted(maps.Keys(compassControlHandlers)), ", ")), nil
	}
	cmd, err := handle(c, msg.Params)
	if err != nil {
		return controlError(controlErrInvalidParams, "invalid params: %v", err), nil
	}
	return ControlReply{Result: c.controlStatus()}, cmd
}

func (c *Compass) controlStatus() map[string]any {
	usage := func(row *computev1.UsageRow) any {
		if row == nil {
			return nil
		}
		return map[string]any{
			"gpu_hours":               row.GpuHours,
			"assigned_idle_gpu_hours": row.AssignedIdleGpuHours,
			"gpu_utilization_ratio":   row.GpuUtilizationRatio,
			"runs":                    row.GetRuns(),
		}
	}
	node := c.selected
	children := []string{}
	for _, child := range node.children {
		children = append(children, child.key)
	}
	selected := map[string]any{
		"path":     node.path(),
		"level":    orNil(node.level),
		"usage":    usage(node.row),
		"children": children,
		"more":     node.more,
	}
	var dataThrough, problem any
	if !c.asOf.IsZero() {
		dataThrough = c.asOf.Format(time.RFC3339)
	}
	if c.err != nil {
		problem = c.err.Error()
	}
	return map[string]any{
		"mode": "compass",
		"url":  c.params.remoteURL(""),
		"tab":  c.tab,
		"scope": map[string]any{
			"org":           orNil(c.params.Org),
			"team":          orNil(cmp.Or(c.params.Entity, c.team)),
			"project":       orNil(c.params.Project),
			"device_models": append([]string{}, c.models...),
			"tags":          append([]string{}, c.tags...),
		},
		"period": map[string]any{
			"name":  c.period,
			"start": c.resolved.GetStart(),
			"end":   c.resolved.GetEnd(),
		},
		"hierarchy":    c.order,
		"basis":        "physical",
		"data_through": dataThrough,
		"total":        usage(c.total),
		"selected":     selected,
		"loading":      c.pending > 0,
		"error":        problem,
	}
}
