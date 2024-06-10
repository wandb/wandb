package runsummary

import "sync"

// Stats struct to hold statistical data
type Stats struct {
	Min    float64
	Max    float64
	Mean   float64
	Count  int     // the number of measurements
	Sum    float64 // the sum of all measurements
	Latest float64 // the latest measurement
}

// update the statistics with a new measurement
func (s *Stats) Update(newVal float64) {
	if s.Count == 0 {
		s.Min = newVal
		s.Max = newVal
		s.Mean = newVal
		s.Sum = newVal
		s.Count = 1
		s.Latest = newVal
	} else {
		s.Count++
		s.Sum += newVal
		s.Mean = s.Sum / float64(s.Count)

		if newVal < s.Min {
			s.Min = newVal
		}
		if newVal > s.Max {
			s.Max = newVal
		}
		s.Latest = newVal
	}
}

type SummaryType int

const (
	Latest SummaryType = iota
	Min
	Max
	Mean
	None
)

type Leaf struct {
	Stats   *Stats
	Summary SummaryType
}

// Node represents a dictionary or a stats holder
type Node struct {
	leaf  *Leaf
	nodes map[string]*Node
	mu    sync.Mutex // Guard access to the map
}

// NewNode creates a new Node
func NewNode() *Node {
	return &Node{
		nodes: make(map[string]*Node),
	}
}

// GetOrCreateNode retrieves or creates a node at a given path
func (n *Node) GetOrCreateNode(path []string) (*Node, error) {
	if len(path) == 0 {
		return n, nil
	}

	n.mu.Lock()
	defer n.mu.Unlock()

	current := n
	for _, p := range path {
		if current.nodes[p] == nil {
			current.nodes[p] = NewNode()
		}
		current = current.nodes[p]
	}

	return current, nil
}

// UpdateStats updates or initializes the stats at the given path
func (n *Node) UpdateStats(path []string, value interface{}, summary SummaryType) error {
	node, err := n.GetOrCreateNode(path)
	if err != nil {
		return err
	}

	if node.leaf == nil {
		node.leaf = &Leaf{
			Stats:   &Stats{},
			Summary: summary,
		}
	}

	// we only need to convert the value to float64 if it is an int or float:
	var update float64
	switch value := value.(type) {
	case int:
		update = float64(value)
	case int32:
		update = float64(value)
	case int64:
		update = float64(value)
	case float32:
		update = float64(value)
	case float64:
		update = value
	default:
		// TODO: handle other types, just do latest probably
		return nil
	}

	node.leaf.Stats.Update(update)
	return nil
}
