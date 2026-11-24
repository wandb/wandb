// Package systemmetrics renders typed system metrics records as the legacy
// string-keyed StatsRecord.
//
// The keys come from the MetricInfo options in
// wandb/proto/wandb_system_metrics.proto, which stays the only catalog of
// system metrics and their legacy keys.
package systemmetrics

import (
	"maps"
	"math"
	"strconv"
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/descriptorpb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Item is one legacy system metric: its key without the "system." prefix and
// the writer label, and its value in the legacy unit.
type Item struct {
	Key   string
	Value float64

	// Integer is whether the field is an integer, so the value's JSON is an
	// integer too.
	Integer bool
}

// JSON returns the item's value as JSON.
func (item Item) JSON() string {
	if item.Integer && item.Value == math.Trunc(item.Value) {
		return strconv.FormatFloat(item.Value, 'f', -1, 64)
	}
	return strconv.FormatFloat(item.Value, 'g', -1, 64)
}

// Items renders the legacy items of a record.
//
// Accelerators with a host get "/l:<host>" after their keys, and fields
// marked legacy_process_copy are repeated under gpu.process.<index>.* for
// devices the monitored process uses.
func Items(rec *spb.SystemMetricsRecord) []Item {
	if rec == nil {
		return nil
	}

	var items []Item
	emit := func(item Item) {
		if math.IsNaN(item.Value) || math.IsInf(item.Value, 0) {
			return
		}
		items = append(items, item)
	}

	walk(rec.ProtoReflect(), scope{}, func(l leaf) { renderLegacy(l, emit) })
	tpuDistributionItems(rec.GetTpuRuntime(), emit)
	return items
}

// StatsRecord returns the legacy StatsRecord for a symon response: the items
// symon still sends as strings, followed by the items rendered from its typed
// sample.
//
// It returns nil when the response has no metrics.
func StatsRecord(response *spb.SubscribeResponse) *spb.StatsRecord {
	stats := response.GetRecord().GetStats()
	sample := response.GetSample()
	if sample == nil {
		return stats
	}

	merged := &spb.StatsRecord{
		StatsType: spb.StatsRecord_SYSTEM,
		Timestamp: sample.GetTimestamp(),
	}
	if stats != nil {
		merged.Timestamp = stats.GetTimestamp()
		merged.Item = append(merged.Item, stats.GetItem()...)
	}
	for _, item := range Items(sample) {
		merged.Item = append(merged.Item, &spb.StatsItem{
			Key:       item.Key,
			ValueJson: item.JSON(),
		})
	}
	if len(merged.Item) == 0 {
		return nil
	}
	return merged
}

// LegacyStats returns the StatsRecord a typed record stands for, with the
// writer's label after every key, or nil when it renders no items.
func LegacyStats(rec *spb.SystemMetricsRecord) *spb.StatsRecord {
	items := Items(rec)
	if len(items) == 0 {
		return nil
	}

	suffix := ""
	if label := rec.GetWriter().GetLabel(); label != "" {
		suffix = "/l:" + label
	}
	stats := &spb.StatsRecord{
		StatsType: spb.StatsRecord_SYSTEM,
		Timestamp: rec.GetTimestamp(),
		Item:      make([]*spb.StatsItem, 0, len(items)),
	}
	for _, item := range items {
		stats.Item = append(stats.Item, &spb.StatsItem{
			Key:       item.Key + suffix,
			ValueJson: item.JSON(),
		})
	}
	return stats
}

// scope carries what a leaf needs from its enclosing messages: the
// accelerator type and source that select a template, the host suffix,
// whether the monitored process uses the device, and the placeholders.
type scope struct {
	accel     spb.AcceleratorType
	source    string
	host      string
	inUse     bool
	partition bool
	vars      map[string]string
}

// child derives the scope of a message from its parent's and the message's
// own identity fields.
func (s scope) child(m protoreflect.Message) scope {
	c := s
	c.vars = make(map[string]string, len(s.vars)+4)
	maps.Copy(c.vars, s.vars)

	fields := m.Descriptor().Fields()
	for i := range fields.Len() {
		fd := fields.Get(i)
		if fd.IsList() || fd.Kind() == protoreflect.MessageKind || metricInfo(fd) != nil {
			continue
		}
		v := m.Get(fd)
		switch fd.Name() {
		case "index", "series":
			c.vars[string(fd.Name())] = strconv.FormatUint(v.Uint(), 10)
		case "path", "device", "label", "name":
			c.vars[string(fd.Name())] = v.String()
		case "source":
			c.vars["source"] = v.String()
			c.source = v.String()
		case "type":
			c.accel = spb.AcceleratorType(v.Enum())
		case "host":
			c.host = v.String()
		case "binding":
			c.inUse = spb.Binding(v.Enum()) == spb.Binding_PROCESS
		case "parent_uuid":
			c.partition = v.String() != ""
		}
	}
	return c
}

// leaf is one measured field of a record.
type leaf struct {
	info    *spb.MetricInfo
	scope   scope
	value   float64 // in info.Unit
	integer bool
}

// walk visits every populated field that has a MetricInfo option.
func walk(m protoreflect.Message, parent scope, visit func(leaf)) {
	s := parent.child(m)
	m.Range(func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		switch {
		case fd.IsMap():
		case fd.IsList() && fd.Kind() == protoreflect.MessageKind:
			list := v.List()
			for i := range list.Len() {
				walk(list.Get(i).Message(), s, visit)
			}
		case fd.Kind() == protoreflect.MessageKind:
			walk(v.Message(), s, visit)
		default:
			if info := metricInfo(fd); info != nil {
				visit(leaf{
					info:  info,
					scope: s,
					value: numeric(fd, v),
					integer: fd.Kind() != protoreflect.DoubleKind &&
						fd.Kind() != protoreflect.FloatKind,
				})
			}
		}
		return true
	})
}

func renderLegacy(l leaf, emit func(Item)) {
	if l.scope.partition {
		return
	}
	lk := pickLegacy(l.info.GetLegacy(), l.scope.accel, l.scope.source)
	if lk == nil {
		return
	}
	item := Item{Value: l.value, Integer: l.integer}
	if unit := lk.GetUnit(); unit != "" && unit != l.info.GetUnit() {
		item.Value = scale(item.Value, unitScale(l.info.GetUnit(), unit))
		item.Integer = false
	}

	item.Key = l.scope.expand(lk.GetTemplate())
	emit(item)
	if l.info.GetLegacyProcessCopy() && l.scope.inUse {
		item.Key = l.scope.expand(strings.Replace(
			lk.GetTemplate(), "gpu.{index}.", "gpu.process.{index}.", 1))
		emit(item)
	}
}

// expand fills a template's placeholders and appends the host suffix.
func (s scope) expand(template string) string {
	key := template
	for name, value := range s.vars {
		key = strings.ReplaceAll(key, "{"+name+"}", value)
	}
	if s.host != "" {
		key += "/l:" + s.host
	}
	return key
}

// pickLegacy selects the most specific template for an accelerator type and
// source: one naming both beats one naming the type, which beats one naming
// the source, which beats one naming neither. Templates naming another type
// or source never match.
func pickLegacy(
	entries []*spb.LegacyKey,
	accel spb.AcceleratorType,
	source string,
) *spb.LegacyKey {
	var best *spb.LegacyKey
	bestScore := -1
	for _, e := range entries {
		score := 0
		if t := e.GetAcceleratorType(); t != spb.AcceleratorType_ACCELERATOR_UNSPECIFIED {
			if t != accel {
				continue
			}
			score += 2
		}
		if src := e.GetSource(); src != "" {
			if src != source {
				continue
			}
			score++
		}
		if score > bestScore {
			best, bestScore = e, score
		}
	}
	return best
}

func numeric(fd protoreflect.FieldDescriptor, v protoreflect.Value) float64 {
	switch fd.Kind() {
	case protoreflect.DoubleKind, protoreflect.FloatKind:
		return v.Float()
	case protoreflect.Uint32Kind, protoreflect.Uint64Kind,
		protoreflect.Fixed32Kind, protoreflect.Fixed64Kind:
		return float64(v.Uint())
	case protoreflect.Int32Kind, protoreflect.Int64Kind,
		protoreflect.Sint32Kind, protoreflect.Sint64Kind,
		protoreflect.Sfixed32Kind, protoreflect.Sfixed64Kind:
		return float64(v.Int())
	default:
		return math.NaN()
	}
}

// unitScale returns the factor from a field's unit to its legacy unit.
func unitScale(from, to string) float64 {
	switch from + ">" + to {
	case "By>MiBy":
		return 1.0 / (1 << 20)
	case "By>GiBy":
		return 1.0 / (1 << 30)
	case "J>mJ":
		return 1000
	case "1>%":
		return 100
	case "Hz>MHz", "bit/s>Mbit/s":
		return 1e-6
	case "s>us":
		return 1e6
	default:
		return 1
	}
}

// scale converts a value to its legacy unit, rounded to 15 significant
// digits so that 0.07 renders as 7 percent rather than 7.000000000000001.
func scale(value, factor float64) float64 {
	rounded, _ := strconv.ParseFloat(strconv.FormatFloat(value*factor, 'g', 15, 64), 64)
	return rounded
}

func metricInfo(fd protoreflect.FieldDescriptor) *spb.MetricInfo {
	opts, ok := fd.Options().(*descriptorpb.FieldOptions)
	if !ok || opts == nil || !proto.HasExtension(opts, spb.E_Metric) {
		return nil
	}
	info, _ := proto.GetExtension(opts, spb.E_Metric).(*spb.MetricInfo)
	return info
}

// tpuDistributionNames are the legacy key names, stat unit suffixes and
// UCUM units of the TPU runtime distributions: tpu.<name>[.<label>].<stat><unit>.
var tpuDistributionNames = map[spb.TpuRuntimeMetrics_DistributionKind][3]string{
	spb.TpuRuntimeMetrics_BUFFER_TRANSFER_LATENCY: {"bufferTransferLatency", "Us", "us"},
	spb.TpuRuntimeMetrics_INBOUND_BUFFER_TRANSFER_LATENCY: {
		"inboundBufferTransferLatency",
		"Us",
		"us",
	},
	spb.TpuRuntimeMetrics_HOST_TO_DEVICE_TRANSFER_LATENCY: {
		"hostToDeviceTransferLatency",
		"Us",
		"us",
	},
	spb.TpuRuntimeMetrics_DEVICE_TO_HOST_TRANSFER_LATENCY: {
		"deviceToHostTransferLatency",
		"Us",
		"us",
	},
	spb.TpuRuntimeMetrics_COLLECTIVE_E2E_LATENCY: {"collectiveE2ELatency", "Us", "us"},
	spb.TpuRuntimeMetrics_HOST_COMPUTE_LATENCY:   {"hostComputeLatency", "Us", "us"},
	spb.TpuRuntimeMetrics_HLO_EXEC_TIMING:        {"hloExecTiming", "Us", "us"},
	spb.TpuRuntimeMetrics_GRPC_TCP_MIN_RTT:       {"grpcTcpMinRtt", "Us", "us"},
	spb.TpuRuntimeMetrics_GRPC_TCP_DELIVERY_RATE: {
		"grpcTcpDeliveryRate",
		"Mbps",
		"Mbit/s",
	},
}

func tpuDistributionItems(tr *spb.TpuRuntimeMetrics, emit func(Item)) {
	for _, d := range tr.GetDistributions() {
		spec, ok := tpuDistributionNames[d.GetKind()]
		if !ok {
			continue
		}
		factor := unitScale(distributionInfo(d.GetKind()).GetUnit(), spec[2])
		base := "tpu." + spec[0]
		if d.GetLabel() != "" {
			base += "." + d.GetLabel()
		}
		stats := []struct {
			name  string
			value *float64
		}{
			{"mean", d.Mean}, {"p50", d.P50}, {"p90", d.P90},
			{"p95", d.P95}, {"p99", d.P99}, {"p999", d.P999},
		}
		for _, stat := range stats {
			if stat.value != nil {
				emit(Item{Key: base + "." + stat.name + spec[1], Value: scale(*stat.value, factor)})
			}
		}
	}
}

func distributionInfo(kind spb.TpuRuntimeMetrics_DistributionKind) *spb.MetricInfo {
	opts := kind.Descriptor().Values().ByNumber(kind.Number()).Options()
	info, _ := proto.GetExtension(opts, spb.E_Distribution).(*spb.MetricInfo)
	return info
}
