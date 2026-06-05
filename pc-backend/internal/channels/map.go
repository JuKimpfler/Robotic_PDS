// Package channels defines the channel map types and CSV/xlsx loading.
package channels

// ChannelDef holds metadata for a single telemetry channel.
type ChannelDef struct {
	Index     int     `json:"index"`
	Name      string  `json:"name"`
	Unit      string  `json:"unit"`
	Scale     float32 `json:"scale"`
	Offset    float32 `json:"offset"`
	Min       float32 `json:"min"`
	Max       float32 `json:"max"`
	Group     string  `json:"group"`
	Color     string  `json:"color"`
	Precision int     `json:"precision"`
	Enabled   bool    `json:"enabled"`
}

// ChannelMap is an ordered slice of channel definitions.
// Index i in the slice corresponds to float32 index i in the SPI frame.
type ChannelMap []ChannelDef

// ByName returns the ChannelDef with the given name, or nil if not found.
func (cm ChannelMap) ByName(name string) *ChannelDef {
	for i := range cm {
		if cm[i].Name == name {
			return &cm[i]
		}
	}
	return nil
}

// Groups returns the unique set of group names in definition order.
func (cm ChannelMap) Groups() []string {
	seen := make(map[string]bool)
	var out []string
	for _, ch := range cm {
		if !seen[ch.Group] {
			seen[ch.Group] = true
			out = append(out, ch.Group)
		}
	}
	return out
}
