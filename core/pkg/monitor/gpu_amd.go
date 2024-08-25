//go:build linux && !libwandb_core

package monitor

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	metrics             map[string][]float64
	GetROCMSMIStatsFunc func() (InfoDict, error)
	IsAvailableFunc     func() bool
	mutex               sync.RWMutex
}

func NewGPUAMD() *GPUAMD {
	g := &GPUAMD{
		name:    "gpu",
		metrics: make(map[string][]float64),
		// this is done this way to be able to mock the function in tests
		GetROCMSMIStatsFunc: getROCMSMIStats,
	}
	return g
}

func (g *GPUAMD) Name() string { return g.name }

func GetRocmSMICmd() (string, error) {
	if foundCmd, err := exec.LookPath("rocm-smi"); err == nil {
		return foundCmd, nil
	}
	// try to use the default path
	if _, err := os.Stat(rocmSMICmd); err == nil {
		return rocmSMICmd, nil
	}
	return "", fmt.Errorf("rocm-smi not found")
}

func (g *GPUAMD) IsAvailable() bool {
	if g.IsAvailableFunc != nil {
		return g.IsAvailableFunc()
	}

	_, err := GetRocmSMICmd()
	if err != nil {
		return false
	}

	isDriverInitialized := false
	fileContent, err := os.ReadFile("/sys/module/amdgpu/initstate")
	if err == nil && strings.Contains(string(fileContent), "live") {
		isDriverInitialized = true
	}

	canReadRocmSmi := false
	if stats, err := getROCMSMIStats(); err == nil {
		// check if stats is not nil or empty
		if len(stats) > 0 {
			canReadRocmSmi = true
		}
	}

	return isDriverInitialized && canReadRocmSmi
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
func (g *GPUAMD) Probe() *spb.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}

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

	info := spb.MetadataRequest{
		GpuAmd: []*spb.GpuAmdInfo{},
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
		gpuInfo := spb.GpuAmdInfo{}
		for key, statKey := range keyMapping {
			if value, ok := queryMapString(stats, statKey); ok {
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
	rocmSMICmd, err := GetRocmSMICmd()
	if err != nil {
		return nil, err
	}
	cmd := exec.Command(rocmSMICmd, "-a", "--json")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var stats InfoDict
	if err := json.Unmarshal(output, &stats); err != nil {
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
			maxPowerWatts, ok := queryMapString(stats, "Max Graphics Package Power (W)")
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
		strVal, ok := queryMapString(stats, key)
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

func (g *GPUAMD) SampleMetrics() error {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	cards := g.getCards()

	for gpu_id, stats := range cards {
		for statKey, value := range stats {
			formattedKey := fmt.Sprintf("%s.%d.%s", g.name, gpu_id, statKey)
			g.metrics[formattedKey] = append(g.metrics[formattedKey], value)
		}
	}

	return nil
}

func parseFloat(s string) (float64, error) {
	var f float64
	_, err := fmt.Sscanf(s, "%f", &f)
	return f, err
}

func (g *GPUAMD) ClearMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.metrics = make(map[string][]float64)
}

func (g *GPUAMD) AggregateMetrics() map[string]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}
