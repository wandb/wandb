package handler

type Node[T any] struct {
	Value    *T                  `json:"value"`
	Name     string              `json:"name"`
	Children map[string]*Node[T] `json:"children"`
}

func NewNode[T any](value *T, name string) *Node[T] {
	return &Node[T]{
		Value:    value,
		Name:     name,
		Children: make(map[string]*Node[T]),
	}
}

func (n *Node[T]) Add(path []string, value *T) {
	if len(path) == 0 {
		n.Value = value
		return
	}
	if _, ok := n.Children[path[0]]; !ok {
		n.Children[path[0]] = NewNode[T](value, path[0])
	}
	n.Children[path[0]].Add(path[1:], value)
}

func (n *Node[T]) Get(path []string) *Node[T] {
	if len(path) == 0 {
		return n
	}
	if _, ok := n.Children[path[0]]; !ok {
		return nil
	}
	return n.Children[path[0]].Get(path[1:])
}

func (n *Node[T]) Remove(path []string) {
	if len(path) == 1 {
		delete(n.Children, path[0])
		return
	}
	if _, ok := n.Children[path[0]]; !ok {
		return
	}
	n.Children[path[0]].Remove(path[1:])
}

func (n *Node[T]) Merge(other *Node[T]) {
	for _, child := range other.Children {
		if _, ok := n.Children[child.Name]; !ok {
			n.Children[child.Name] = child
			continue
		}
		n.Children[child.Name].Merge(child)
	}
}

type Key struct {
	Path []string
}

func (n *Node[T]) Flatten() map[*Key]*T {
	flat := make(map[*Key]*T)
	for _, child := range n.Children {
		for k, v := range child.Flatten() {
			flat[&Key{append([]string{child.Name}, k.Path...)}] = v
		}
	}
	if n.Value != nil {
		flat[&Key{[]string{n.Name}}] = n.Value
	}
	return flat
}
