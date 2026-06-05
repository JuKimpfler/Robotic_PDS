// Package channels — CSV and xlsx loader for channel definitions.
package channels

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/xuri/excelize/v2"
)

// LoadCSV reads a channels.csv file and returns a validated ChannelMap.
// Comment lines (starting with #) and blank lines are skipped.
func LoadCSV(path string) (ChannelMap, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("channels: open %q: %w", path, err)
	}
	defer f.Close()

	var channels ChannelMap
	scanner := bufio.NewScanner(f)
	lineNum := 0
	headerSkipped := false

	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())

		// Skip blanks and comments
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Skip the header row
		if !headerSkipped && strings.HasPrefix(line, "index,") {
			headerSkipped = true
			continue
		}

		ch, err := parseCSVRow(line, lineNum)
		if err != nil {
			return nil, err
		}
		channels = append(channels, ch)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("channels: scan %q: %w", path, err)
	}

	if err := validateChannelMap(channels); err != nil {
		return nil, err
	}
	return channels, nil
}

func parseCSVRow(line string, lineNum int) (ChannelDef, error) {
	parts := strings.Split(line, ",")
	if len(parts) < 11 {
		return ChannelDef{}, fmt.Errorf("channels: line %d: expected 11 fields, got %d", lineNum, len(parts))
	}

	idx, err := strconv.Atoi(strings.TrimSpace(parts[0]))
	if err != nil {
		return ChannelDef{}, fmt.Errorf("channels: line %d: invalid index %q", lineNum, parts[0])
	}

	scale, _ := strconv.ParseFloat(strings.TrimSpace(parts[3]), 32)
	offset, _ := strconv.ParseFloat(strings.TrimSpace(parts[4]), 32)
	min, _ := strconv.ParseFloat(strings.TrimSpace(parts[5]), 32)
	max, _ := strconv.ParseFloat(strings.TrimSpace(parts[6]), 32)
	precision, _ := strconv.Atoi(strings.TrimSpace(parts[9]))
	enabled := strings.TrimSpace(strings.ToLower(parts[10])) == "true"

	return ChannelDef{
		Index:     idx,
		Name:      strings.TrimSpace(parts[1]),
		Unit:      strings.TrimSpace(parts[2]),
		Scale:     float32(scale),
		Offset:    float32(offset),
		Min:       float32(min),
		Max:       float32(max),
		Group:     strings.TrimSpace(parts[7]),
		Color:     strings.TrimSpace(parts[8]),
		Precision: precision,
		Enabled:   enabled,
	}, nil
}

// validateChannelMap checks that indices are contiguous starting at 0.
func validateChannelMap(cm ChannelMap) error {
	for i, ch := range cm {
		if ch.Index != i {
			return fmt.Errorf("channels: index gap at position %d (expected %d, got %d)", i, i, ch.Index)
		}
	}
	return nil
}

// ImportXLSX converts the first sheet of an xlsx file to CSV,
// saves it to outCSVPath, and returns the parsed ChannelMap.
func ImportXLSX(xlsxPath, outCSVPath string) (ChannelMap, error) {
	xl, err := excelize.OpenFile(xlsxPath)
	if err != nil {
		return nil, fmt.Errorf("channels: open xlsx %q: %w", xlsxPath, err)
	}
	defer xl.Close()

	sheets := xl.GetSheetList()
	if len(sheets) == 0 {
		return nil, fmt.Errorf("channels: xlsx has no sheets")
	}

	rows, err := xl.GetRows(sheets[0])
	if err != nil {
		return nil, fmt.Errorf("channels: xlsx get rows: %w", err)
	}

	// Ensure output directory exists
	if err := os.MkdirAll(filepath.Dir(outCSVPath), 0o755); err != nil {
		return nil, err
	}

	out, err := os.Create(outCSVPath)
	if err != nil {
		return nil, fmt.Errorf("channels: create csv %q: %w", outCSVPath, err)
	}
	defer out.Close()

	w := bufio.NewWriter(out)
	for _, row := range rows {
		fmt.Fprintln(w, strings.Join(row, ","))
	}
	w.Flush()

	return LoadCSV(outCSVPath)
}
