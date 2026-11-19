package leet

import (
	"cmp"
	"io"
	"math"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	computev1 "github.com/wandb/wandb/core/internal/leet/computeproto"
)

// ComputeUsageQuery selects server-defined compute usage for a remote scope.
type ComputeUsageQuery struct {
	Period       string   `json:"period"       doc:"YYYY-MM, inclusive YYYY-MM-DD:YYYY-MM-DD, or Nd ending today in UTC. Defaults to 30d."`
	Basis        string   `json:"basis"        doc:"GPU-hour basis: associated, physical or allocated. Defaults to physical."`
	GroupBy      []string `json:"group_by"     doc:"Group by team, project, user, run, device, parent_device, device_model or day."`
	User         string   `json:"user"         doc:"Keep runs owned by this user."`
	Tags         []string `json:"tag"          doc:"Keep runs carrying every tag. Repeatable."`
	DeviceModels []string `json:"device_model" doc:"Keep these device models. Repeatable."`
	DeviceTypes  []string `json:"device_type"  doc:"Keep these device types. Repeatable."`
	Compare      bool     `json:"compare"      doc:"Also query the preceding equal-length period, or previous calendar month for YYYY-MM."`
}

// QueryComputeUsage writes the Compute API's usage with the LEET envelope.
func QueryComputeUsage(params *RemoteRunParams, q ComputeUsageQuery, w io.Writer) error {
	period, previous, err := computePeriods(cmp.Or(q.Period, "30d"), time.Now().UTC())
	if err != nil {
		return err
	}
	basis, ok := computev1.Basis_value["BASIS_"+strings.ToUpper(cmp.Or(q.Basis, "physical"))]
	if !ok || basis == 0 {
		return badRequest("basis must be associated, physical or allocated")
	}
	groups := make([]computev1.GroupBy, 0, len(q.GroupBy))
	for _, name := range q.GroupBy {
		group, ok := computev1.GroupBy_value["GROUP_BY_"+strings.ToUpper(name)]
		if !ok || group == 0 {
			return badRequest("unknown group-by %q", name)
		}
		groups = append(groups, computev1.GroupBy(group))
	}
	req := &computev1.ComputeUsageRequest{
		Scope: &computev1.Scope{
			Org: params.Org, Team: params.Entity, Project: params.Project,
			User: q.User, Tags: q.Tags,
		},
		Period: period, Basis: computev1.Basis(basis), GroupBy: groups,
	}
	if len(q.DeviceModels) > 0 || len(q.DeviceTypes) > 0 {
		req.Filters = &computev1.Filters{DeviceModels: q.DeviceModels, DeviceTypes: q.DeviceTypes}
	}
	if params.RunID != "" {
		req.Scope.Runs = []string{params.RunID}
	}
	clients, err := newComputeClients(params.BaseURL)
	if err != nil {
		return err
	}
	response := &computev1.ComputeUsageResponse{}
	if err := clients.computeCall(params.BaseURL, "ComputeUsage", req, response); err != nil {
		return err
	}
	out, err := computeJSON(response)
	if err != nil {
		return err
	}
	if q.Compare {
		req.Period = previous
		comparison := &computev1.ComputeUsageResponse{}
		if err := clients.computeCall(params.BaseURL, "ComputeUsage", req, comparison); err != nil {
			return err
		}
		other, err := computeJSON(comparison)
		if err != nil {
			return err
		}
		out["compare"] = map[string]any{"period": other["period"], "rows": other["rows"]}
	}
	return writeComputeJSON(w, "usage", params, out)
}

// computePeriods resolves inclusive UTC dates and their comparison period.
func computePeriods(value string, now time.Time) (*computev1.Period, *computev1.Period, error) {
	var start, end time.Time
	var err error
	switch {
	case len(value) == 7 && value[4] == '-':
		start, err = time.Parse("2006-01", value)
		end = start.AddDate(0, 1, -1)
	case strings.HasSuffix(value, "d"):
		var days uint64
		days, err = strconv.ParseUint(strings.TrimSuffix(value, "d"), 10, 32)
		if err == nil && days > 0 {
			end = time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
			start = end.AddDate(0, 0, 1-int(days))
		}
	default:
		first, last, _ := strings.Cut(value, ":")
		start, err = time.Parse(time.DateOnly, first)
		if err == nil {
			end, err = time.Parse(time.DateOnly, last)
		}
	}
	if err != nil || start.IsZero() || end.Before(start) || start.Year() < 1 {
		return nil, nil, badRequest(
			"period must be YYYY-MM, inclusive YYYY-MM-DD:YYYY-MM-DD, or a positive Nd")
	}
	previousEnd := start.AddDate(0, 0, -1)
	// Unix days avoid time.Duration's limit for long explicit date ranges.
	days := (end.Unix()-start.Unix())/86400 + 1
	previousStart := previousEnd.AddDate(0, 0, 1-int(days))
	if len(value) == 7 && value[4] == '-' {
		previousStart = start.AddDate(0, -1, 0)
	}
	period := func(first, last time.Time) *computev1.Period {
		return &computev1.Period{
			Start: first.Format(time.DateOnly),
			End:   last.Format(time.DateOnly),
		}
	}
	return period(start, end), period(previousStart, previousEnd), nil
}

// ComputeDrilldownQuery selects typed fields of the devices in one remote run.
type ComputeDrilldownQuery struct {
	Fields []string `json:"fields" doc:"Typed record field paths, such as accelerators.nvidia.sm_active_ratio. Required."`
	Bins   int      `json:"bins"   doc:"Number of equal time bins. Defaults to 200."`
	Device string   `json:"device" doc:"Keep one device by UUID."`
	Start  string   `json:"start"  doc:"First sample time as RFC3339."`
	End    string   `json:"end"    doc:"Last sample time as RFC3339."`
}

// QueryComputeDrilldown writes device series using history's bin keys.
func QueryComputeDrilldown(params *RemoteRunParams, q ComputeDrilldownQuery, w io.Writer) error {
	if params.RunID == "" {
		return badRequest("a run URL is required")
	}
	if len(q.Fields) == 0 {
		return badRequest("fields is required")
	}
	for _, field := range q.Fields {
		if strings.TrimSpace(field) == "" {
			return badRequest("fields must contain field paths")
		}
	}
	bins := cmp.Or(q.Bins, 200)
	if bins < 1 || uint64(bins) > math.MaxUint32 {
		return badRequest("bins must be between 1 and %d", uint64(math.MaxUint32))
	}
	start, err := computeTimestamp(q.Start)
	if err != nil {
		return err
	}
	end, err := computeTimestamp(q.End)
	if err != nil {
		return err
	}
	if start != nil && end != nil && end.AsTime().Before(start.AsTime()) {
		return badRequest("end must not precede start")
	}
	req := &computev1.ComputeDrilldownRequest{
		Team: params.Entity, Project: params.Project, Run: params.RunID,
		Fields: q.Fields, Bins: uint32(bins), Device: q.Device, Start: start, End: end,
	}
	clients, err := newComputeClients(params.BaseURL)
	if err != nil {
		return err
	}
	response := &computev1.ComputeDrilldownResponse{}
	if err := clients.computeCall(params.BaseURL, "ComputeDrilldown", req, response); err != nil {
		return err
	}
	out, err := computeJSON(response)
	if err != nil {
		return err
	}
	for i, entry := range response.GetSeries() {
		series := out["series"].([]any)[i].(map[string]any)
		for j, bin := range entry.GetBins() {
			item := series["bins"].([]any)[j].(map[string]any)
			delete(item, "start")
			item["x0"], item["x1"] = nil, nil
			if bin.Start != nil {
				x0 := computeSeconds(bin.Start)
				item["x0"] = x0
				if response.Start != nil && response.End != nil {
					end := computeSeconds(response.End)
					width := (end - computeSeconds(response.Start)) / float64(bins)
					item["x1"] = min(x0+width, end)
				}
			}
			item["has_nan"] = false
		}
	}
	return writeComputeJSON(w, "drilldown", params, out)
}

func computeTimestamp(value string) (*timestamppb.Timestamp, error) {
	if value == "" {
		return nil, nil
	}
	at, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return nil, badRequest("start and end must be RFC3339 timestamps")
	}
	timestamp := timestamppb.New(at)
	if err := timestamp.CheckValid(); err != nil {
		return nil, badRequest("invalid timestamp: %s", err)
	}
	return timestamp, nil
}

func computeSeconds(at *timestamppb.Timestamp) float64 {
	return float64(at.GetSeconds()) + float64(at.GetNanos())/1e9
}
