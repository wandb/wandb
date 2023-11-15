//go:build linux && !libwandb_core

package monitor

import (
	"encoding/json"
	"fmt"
	"log"
	"os/exec"
	"strings"
	"sync"
)

// TODO: this is a port of the python code
// should eventually switch to https://github.com/amd/go_amd_smi

const rocmSMICmd string = "/usr/bin/rocm-smi"

type StatsKeys string

const (
	GPU             StatsKeys = "gpu"
	MemoryAllocated           = "memoryAllocated"
	Temp                      = "temp"
	PowerWatts                = "powerWatts"
	PowerPercent              = "powerPercent"
)

type Stats map[StatsKeys]float64

type InfoDict map[string]interface{}

type GPUAMDStats struct {
	name    string
	samples []Stats
	mutex   sync.Mutex
}

func NewGPUAMDStats() *GPUAMDStats {
	return &GPUAMDStats{
		name:    "gpu",
		samples: make([]Stats, 0),
	}
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

func (g *GPUAMDStats) parseStats(stats map[string]string) Stats {
	parsedStats := make(Stats)

	gpuUsage, err := parseFloat(stats["GPU use (%)"])
	if err == nil {
		parsedStats[GPU] = gpuUsage
	}

	memoryUsage, err := parseFloat(stats["GPU memory use (%)"])
	if err == nil {
		parsedStats[MemoryAllocated] = memoryUsage
	}

	temp, err := parseFloat(stats["Temperature (Sensor memory) (C)"])
	if err == nil {
		parsedStats[Temp] = temp
	}

	powerWatts, err := parseFloat(stats["Average Graphics Package Power (W)"])
	if err == nil {
		parsedStats[PowerWatts] = powerWatts
	}

	maxPower, errMax := parseFloat(stats["Max Graphics Package Power (W)"])
	if err == nil && errMax == nil && maxPower != 0 {
		parsedStats[PowerPercent] = (powerWatts / maxPower) * 100
	}

	return parsedStats
}

func parseFloat(s string) (float64, error) {
	var f float64
	_, err := fmt.Sscanf(s, "%f", &f)
	return f, err
}

func (g *GPUAMDStats) Sample() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	rawStats, err := getROCMSMIStats()
	if err != nil {
		log.Printf("Error getting ROCm SMI stats: %v", err)
		return
	}

	var cards []Stats
	for key, value := range rawStats {
		if strings.HasPrefix(key, "card") {
			cardStats, ok := value.(map[string]string)
			if !ok {
				continue
			}
			stats := g.parseStats(cardStats)
			cards = append(cards, stats)
		}
	}

	if len(cards) > 0 {
		g.samples = append(g.samples, cards...)
	}
}

func (g *GPUAMDStats) Clear() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.samples = make([]Stats, 0)
}

func (g *GPUAMDStats) Aggregate() map[string]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	aggregates := make(map[string]float64)
	for _, sample := range g.samples {
		for key, value := range sample {
			aggregates[string(key)] += value
		}
	}

	for key := range aggregates {
		aggregates[key] /= float64(len(g.samples))
	}

	return aggregates
}
