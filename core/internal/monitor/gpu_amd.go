//go:build linux && !libwandb_core

package monitor

import (
	"fmt"
	"log"
	"os/exec"
	"strings"
	"sync"

	"github.com/segmentio/encoding/json"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

// TODO: this is a port of the python code
// should eventually switch to https://github.com/amd/go_amd_smi

const rocmSMICmd string = "/usr/bin/rocm-smi"

type StatsKeys string

const (
	GPU             StatsKeys = "gpu"
	MemoryAllocated StatsKeys = "memoryAllocated"
	Temp            StatsKeys = "temp"
	PowerWatts      StatsKeys = "powerWatts"
	PowerPercent    StatsKeys = "powerPercent"
)

type Stats map[StatsKeys]float64

type InfoDict map[string]interface{}

type GPUAMD struct {
	name                string
	settings            *pb.Settings
	metrics             map[string][]float64
	GetROCMSMIStatsFunc func() (InfoDict, error)
	mutex               sync.RWMutex
}

func NewGPUAMD(settings *pb.Settings) *GPUAMD {
	g := &GPUAMD{
		name:     "gpu",
		settings: settings,
		metrics:  make(map[string][]float64),
		// this is done this way to be able to mock the function in tests
		GetROCMSMIStatsFunc: getROCMSMIStats,
	}
	return g
}

func (g *GPUAMD) Name() string { return g.name }

func (g *GPUAMD) IsAvailable() bool {
	_, err := exec.LookPath(rocmSMICmd)
	return err == nil
}

func (g *GPUAMD) getCards() map[int]Stats {

	rawStats, err := g.GetROCMSMIStatsFunc()
	if err != nil {
		log.Printf("Error getting ROCm SMI stats: %v", err)
		return nil
	}

	cards := make(map[int]Stats)
	for key, value := range rawStats {
		if strings.HasPrefix(key, "card") {
			// get card id and convert it to int
			var cardID int
			s := strings.TrimPrefix(key, "card")
			_, err := fmt.Sscanf(s, "%d", &cardID)
			if err != nil {
				continue
			}
			cardStats, ok := value.(map[string]interface{})
			if !ok {
				log.Printf("Type assertion failed for key %s", key)
				continue
			}
			stats := g.ParseStats(cardStats)
			cards[cardID] = stats
		}
	}
	return cards
}

//gocyclo:ignore
func (g *GPUAMD) Probe() *pb.MetadataRequest {

	rawStats, err := g.GetROCMSMIStatsFunc()
	if err != nil {
		log.Printf("Error getting ROCm SMI stats: %v", err)
		return nil
	}

	cards := make(map[int]map[string]interface{})
	for key, value := range rawStats {
		if strings.HasPrefix(key, "card") {
			// get card id and convert it to int
			var cardID int
			s := strings.TrimPrefix(key, "card")
			_, err := fmt.Sscanf(s, "%d", &cardID)
			if err != nil {
				continue
			}
			stats, ok := value.(map[string]interface{})
			if !ok {
				log.Printf("Type assertion failed for key %s", key)
				continue
			}
			cards[cardID] = stats
		}
	}

	info := pb.MetadataRequest{
		GpuAmd: []*pb.GpuAmdInfo{},
	}

	info.GpuCount = uint32(len(cards))

	keyMapping := map[string]string{
		"Id":                 "GPU ID",
		"UniqueId":           "Unique ID",
		"VbiosVersion":       "VBIOS version",
		"PerformanceLevel":   "Performance Level",
		"GpuOverdrive":       "GPU OverDrive value (%)",
		"GpuMemoryOverdrive": "GPU Memory OverDrive value (%)",
		"MaxPower":           "Max Graphics Package Power (W)",
		"Series":             "Card series",
		"Model":              "Card model",
		"Vendor":             "Card vendor",
		"Sku":                "Card SKU",
		"SclkRange":          "Valid sclk range",
		"MclkRange":          "Valid mclk range",
	}

	for _, stats := range cards {
		gpuInfo := pb.GpuAmdInfo{}
		for key, statKey := range keyMapping {
			if value, ok := stats[statKey].(string); ok {
				switch key {
				case "Id":
					gpuInfo.Id = value
				case "UniqueId":
					gpuInfo.UniqueId = value
				case "VbiosVersion":
					gpuInfo.VbiosVersion = value
				case "PerformanceLevel":
					gpuInfo.PerformanceLevel = value
				case "GpuOverdrive":
					gpuInfo.GpuOverdrive = value
				case "GpuMemoryOverdrive":
					gpuInfo.GpuMemoryOverdrive = value
				case "MaxPower":
					gpuInfo.MaxPower = value
				case "Series":
					gpuInfo.Series = value
				case "Model":
					gpuInfo.Model = value
				case "Vendor":
					gpuInfo.Vendor = value
				case "Sku":
					gpuInfo.Sku = value
				case "SclkRange":
					gpuInfo.SclkRange = value
				case "MclkRange":
					gpuInfo.MclkRange = value
				}
			}
		}
		info.GpuAmd = append(info.GpuAmd, &gpuInfo)
	}

	return &info
}

func (g *GPUAMD) Samples() map[string][]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	return g.metrics
}

func getROCMSMIStats() (InfoDict, error) {
	cmd := exec.Command(rocmSMICmd, "-a", "--json")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var stats InfoDict
	err = json.Unmarshal(output, &stats)
	if err != nil {
		return nil, err
	}
	return stats, nil
}

func (g *GPUAMD) ParseStats(stats map[string]interface{}) Stats {
	parsedStats := make(Stats)

	for key, statFunc := range map[string]func(string) *Stats{
		"GPU use (%)": func(s string) *Stats {
			if f, err := parseFloat(s); err == nil {
				return &Stats{GPU: f}
			}
			return nil
		},
		"GPU memory use (%)": func(s string) *Stats {
			if f, err := parseFloat(s); err == nil {
				return &Stats{MemoryAllocated: f}
			}
			return nil
		},
		"Temperature (Sensor memory) (C)": func(s string) *Stats {
			if f, err := parseFloat(s); err == nil {
				return &Stats{Temp: f}
			}
			return nil
		},
		"Average Graphics Package Power (W)": func(s string) *Stats {
			maxPowerWatts, ok := stats["Max Graphics Package Power (W)"].(string)
			if !ok {
				return nil
			}
			mp, err1 := parseFloat(maxPowerWatts)
			ap, err2 := parseFloat(s)

			if err1 == nil && err2 == nil && mp != 0 {
				powerStats := Stats{PowerWatts: ap, PowerPercent: (ap / mp) * 100}
				return &powerStats
			}
			return nil
		},
	} {
		strVal, ok := stats[key].(string)
		if ok {
			partialStats := statFunc(strVal)
			if partialStats != nil {
				for k, v := range *partialStats {
					parsedStats[k] = v
				}
			}
		}
	}

	return parsedStats
}

func (g *GPUAMD) SampleMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	cards := g.getCards()

	for gpu_id, stats := range cards {
		for statKey, value := range stats {
			formattedKey := fmt.Sprintf("%s.%d.%s", g.name, gpu_id, statKey)
			g.metrics[formattedKey] = append(g.metrics[formattedKey], value)
		}
	}
}

func parseFloat(s string) (float64, error) {
	var f float64
	_, err := fmt.Sscanf(s, "%f", &f)
	return f, err
}

func (g *GPUAMD) ClearMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	g.metrics = make(map[string][]float64)
}

func (g *GPUAMD) AggregateMetrics() map[string]float64 {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}
