package nfs

import (
	"os"
	"path"
	"strings"
	"time"
)

// NodeType represents the type of virtual node in the filesystem.
type NodeType int

const (
	NodeTypeRoot             NodeType = iota // /
	NodeTypeArtifactsDir                     // /artifacts
	NodeTypeTypesDir                         // /artifacts/types
	NodeTypeCollectionsDir                   // /artifacts/collections
	NodeTypeArtifactType                     // /artifacts/types/{type}
	NodeTypeCollectionSymlink                // /artifacts/types/{type}/{collection} -> symlink
	NodeTypeCollection                       // /artifacts/collections/{collection}
	NodeTypeVersion                          // .../v0, v1, etc.
	NodeTypeMetadataJSON                     // .../metadata.json
	NodeTypeFilesDir                         // .../files/
	NodeTypeFile                             // actual artifact file
)

// VirtualNode represents a node in the virtual filesystem tree.
type VirtualNode struct {
	ID            uint64
	Name          string
	Type          NodeType
	IsDir         bool
	IsSymlink     bool
	SymlinkTarget string // For symlinks, the target path

	Parent   *VirtualNode
	Children map[string]*VirtualNode

	// Lazy loading state
	Loaded  bool
	LoadErr error

	// Metadata depending on node type
	ArtifactID     string // For version nodes
	ArtifactType   string // Type name
	CollectionName string // Collection name
	VersionIndex   int    // Version number

	// File metadata for file nodes
	FileSize  int64
	DirectURL string // Download URL for file content
	MD5       string // Base64 MD5 hash for cache key

	// Timestamps
	ModTime time.Time
	ATime   time.Time
	CTime   time.Time
}

// NewVirtualNode creates a new virtual node.
func NewVirtualNode(id uint64, name string, nodeType NodeType, isDir bool) *VirtualNode {
	now := time.Now()
	return &VirtualNode{
		ID:       id,
		Name:     name,
		Type:     nodeType,
		IsDir:    isDir,
		Children: make(map[string]*VirtualNode),
		ModTime:  now,
		ATime:    now,
		CTime:    now,
	}
}

// NewSymlinkNode creates a new symlink node.
func NewSymlinkNode(id uint64, name string, target string) *VirtualNode {
	now := time.Now()
	return &VirtualNode{
		ID:            id,
		Name:          name,
		Type:          NodeTypeCollectionSymlink,
		IsDir:         false, // Symlinks are not directories
		IsSymlink:     true,
		SymlinkTarget: target,
		Children:      make(map[string]*VirtualNode),
		ModTime:       now,
		ATime:         now,
		CTime:         now,
	}
}

// FullPath returns the full path from root to this node.
func (n *VirtualNode) FullPath() string {
	if n.Parent == nil {
		return "/"
	}

	parts := []string{}
	current := n
	for current != nil && current.Parent != nil {
		parts = append([]string{current.Name}, parts...)
		current = current.Parent
	}

	return "/" + strings.Join(parts, "/")
}

// AddChild adds a child node.
func (n *VirtualNode) AddChild(child *VirtualNode) {
	child.Parent = n
	n.Children[child.Name] = child
}

// GetChild returns a child by name.
func (n *VirtualNode) GetChild(name string) (*VirtualNode, bool) {
	child, ok := n.Children[name]
	return child, ok
}

// FindByPath finds a node by path from this node.
// Returns the node and any remaining path parts that couldn't be resolved.
func (n *VirtualNode) FindByPath(pathStr string) (*VirtualNode, []string) {
	// Normalize path
	pathStr = path.Clean(pathStr)
	if pathStr == "/" || pathStr == "." || pathStr == "" {
		return n, nil
	}

	// Remove leading slash
	pathStr = strings.TrimPrefix(pathStr, "/")
	parts := strings.Split(pathStr, "/")

	return n.findByParts(parts)
}

func (n *VirtualNode) findByParts(parts []string) (*VirtualNode, []string) {
	if len(parts) == 0 {
		return n, nil
	}

	child, ok := n.Children[parts[0]]
	if !ok {
		return n, parts
	}

	return child.findByParts(parts[1:])
}

// GetFileInfo returns a WandBFileInfo for this node.
func (n *VirtualNode) GetFileInfo() *WandBFileInfo {
	mode := os.FileMode(0o755)
	if !n.IsDir {
		mode = os.FileMode(0o644)
	}
	if n.IsSymlink {
		mode = os.FileMode(0o777) | os.ModeSymlink
	}

	numLinks := 1
	if n.IsDir {
		numLinks = 2 + len(n.Children)
	}

	return &WandBFileInfo{
		id:       n.ID,
		name:     n.Name,
		size:     n.FileSize,
		mode:     mode,
		modTime:  n.ModTime,
		aTime:    n.ATime,
		cTime:    n.CTime,
		isDir:    n.IsDir,
		numLinks: numLinks,
	}
}

// ChildNames returns the names of all children.
func (n *VirtualNode) ChildNames() []string {
	names := make([]string, 0, len(n.Children))
	for name := range n.Children {
		names = append(names, name)
	}
	return names
}

// ChildFileInfos returns FileInfo for all children.
func (n *VirtualNode) ChildFileInfos() []*WandBFileInfo {
	infos := make([]*WandBFileInfo, 0, len(n.Children))
	for _, child := range n.Children {
		infos = append(infos, child.GetFileInfo())
	}
	return infos
}
