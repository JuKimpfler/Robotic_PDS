package ratecontrol

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const presetsDir = "presets"

// PresetEntry is a single index+value pair stored in a named preset file.
type PresetEntry struct {
	Index int     `json:"index"`
	Value float32 `json:"value"`
}

// ListPresets returns the names of all saved preset files (without .json extension).
func ListPresets() ([]string, error) {
	entries, err := os.ReadDir(presetsDir)
	if os.IsNotExist(err) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	var names []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		names = append(names, strings.TrimSuffix(e.Name(), ".json"))
	}
	return names, nil
}

// SavePreset writes a named preset to disk as presets/{name}.json.
func SavePreset(name string, entries []PresetEntry) error {
	if err := os.MkdirAll(presetsDir, 0o755); err != nil {
		return fmt.Errorf("presets: mkdir: %w", err)
	}
	path := filepath.Join(presetsDir, sanitizePresetName(name)+".json")
	b, err := json.MarshalIndent(entries, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o644)
}

// LoadPreset reads a named preset from disk.
func LoadPreset(name string) ([]PresetEntry, error) {
	path := filepath.Join(presetsDir, sanitizePresetName(name)+".json")
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("presets: load %q: %w", name, err)
	}
	var entries []PresetEntry
	if err := json.Unmarshal(b, &entries); err != nil {
		return nil, fmt.Errorf("presets: parse %q: %w", name, err)
	}
	return entries, nil
}

func sanitizePresetName(name string) string {
	name = strings.TrimSpace(name)
	name = strings.ReplaceAll(name, "..", "")
	name = strings.ReplaceAll(name, string(os.PathSeparator), "_")
	return name
}
