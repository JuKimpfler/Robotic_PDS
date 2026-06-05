package ratecontrol

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// ParamDef represents a single tunable robot parameter.
type ParamDef struct {
	Index       int     `json:"index"`
	Name        string  `json:"name"`
	Type        string  `json:"type"` // float32 | int32 | bool
	Default     float32 `json:"default"`
	Min         float32 `json:"min"`
	Max         float32 `json:"max"`
	Unit        string  `json:"unit"`
	Group       string  `json:"group"`
	Description string  `json:"description"`
	Value       float32 `json:"value"` // current active value
}

// LoadParameters parses parameters.csv and returns a slice of ParamDef.
func LoadParameters(path string) ([]ParamDef, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("params: open %q: %w", path, err)
	}
	defer f.Close()

	var list []ParamDef
	scanner := bufio.NewScanner(f)
	lineNum := 0
	headerSkipped := false

	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if !headerSkipped && strings.HasPrefix(line, "index,") {
			headerSkipped = true
			continue
		}

		p, err := parseParamRow(line, lineNum)
		if err != nil {
			return nil, err
		}
		list = append(list, p)
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("params: scan %q: %w", path, err)
	}

	return list, nil
}

func parseParamRow(line string, lineNum int) (ParamDef, error) {
	parts := strings.Split(line, ",")
	if len(parts) < 9 {
		return ParamDef{}, fmt.Errorf("params: line %d: expected at least 9 fields, got %d", lineNum, len(parts))
	}

	idx, err := strconv.Atoi(strings.TrimSpace(parts[0]))
	if err != nil {
		return ParamDef{}, fmt.Errorf("params: line %d: invalid index %q", lineNum, parts[0])
	}

	name := strings.TrimSpace(parts[1])
	pType := strings.TrimSpace(parts[2])

	defVal, _ := strconv.ParseFloat(strings.TrimSpace(parts[3]), 32)
	minVal, _ := strconv.ParseFloat(strings.TrimSpace(parts[4]), 32)
	maxVal, _ := strconv.ParseFloat(strings.TrimSpace(parts[5]), 32)
	unit := strings.TrimSpace(parts[6])
	group := strings.TrimSpace(parts[7])
	desc := strings.TrimSpace(parts[8])

	return ParamDef{
		Index:       idx,
		Name:        name,
		Type:        pType,
		Default:     float32(defVal),
		Min:         float32(minVal),
		Max:         float32(maxVal),
		Unit:        unit,
		Group:       group,
		Description: desc,
		Value:       float32(defVal),
	}, nil
}

// AddMethods to Controller for parameters access
func (c *Controller) SetParamsList(list []ParamDef) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.params = list
}

func (c *Controller) GetParamsList() []ParamDef {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]ParamDef, len(c.params))
	copy(out, c.params)
	return out
}

func (c *Controller) UpdateParamLocal(index int, val float32) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for i := range c.params {
		if c.params[i].Index == index {
			c.params[i].Value = val
			break
		}
	}
}
