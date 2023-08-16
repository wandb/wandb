package main

import (
	"fmt"
)

type TrieNode struct {
	Children map[byte]*TrieNode
	IsLeaf   bool
	Data     interface{}
}

func insertPattern(root *TrieNode, pattern string, data interface{}) {
	node := root
	for i := 0; i < len(pattern); i++ {
		char := pattern[i]
		if _, ok := node.Children[char]; !ok {
			node.Children[char] = &TrieNode{Children: make(map[byte]*TrieNode)}
		}
		node = node.Children[char]
	}
	node.IsLeaf = true
	node.Data = data
}

func matchPattern(node *TrieNode, key string) (bool, interface{}) {
	if len(key) == 0 {
		return node.IsLeaf, node.Data
	}

	char := key[0]

	if child, ok := node.Children[char]; ok {
		return matchPattern(child, key[1:])
	} else if child, ok = node.Children['*']; ok {
		return matchPattern(child, key[1:])
	}

	return node.IsLeaf, node.Data
}

func printTrie(node *TrieNode, prefix string) {
	if node == nil {
		return
	}

	for char, child := range node.Children {
		fmt.Printf("%s[%c]\n", prefix, char)
		printTrie(child, prefix+"  ")
	}

	if node.IsLeaf {
		fmt.Printf("%s[leaf]\n", prefix)
	}
}

func main() {
	globPatterns := []string{
		"abc*",
		"test*",
	}

	root := &TrieNode{Children: make(map[byte]*TrieNode)}

	for _, pattern := range globPatterns {
		insertPattern(root, pattern, "data")
	}

	printTrie(root, "")

	keysToCheck := []string{
		"abcdef",
		"foobar",
		"testing",
		"invalid",
	}

	for _, key := range keysToCheck {
		if m, _ := matchPattern(root, key); m {
			fmt.Printf("%s matches a pattern\n", key)
		} else {
			fmt.Printf("%s does not match any pattern\n", key)
		}
	}
}
