// Package hotspot — PowerShell WinRT wrapper for Windows Mobile Hotspot.
// Implements §4 of the spec exactly.
package hotspot

import (
	"fmt"
	"os/exec"
	"strings"
	"sync"
)

// State represents the current hotspot status.
type State string

const (
	StateOn            State = "on"
	StateOff           State = "off"
	StateTransitioning State = "transitioning"
)

// NOTE: NetworkOperatorTetheringManager requires the process to run as the
// logged-in user (NOT elevated/Admin). Firewall rule is set by install_windows.ps1.

const psStart = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
         Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation,
         Windows.Networking.Connectivity, ContentType=WindowsRuntime]

$profile  = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
$manager  = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)

$newCfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
$newCfg.Ssid       = "%s"
$newCfg.Passphrase = "%s"
$manager.ConfigureAccessPointAsync($newCfg).AsTask().Wait()
$manager.StartTetheringAsync().AsTask().Wait()
Write-Output "OK"
`

const psStop = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
         Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation,
         Windows.Networking.Connectivity, ContentType=WindowsRuntime]
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$manager.StopTetheringAsync().AsTask().Wait()
Write-Output "OK"
`

const psStatus = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
         Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation,
         Windows.Networking.Connectivity, ContentType=WindowsRuntime]
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$status = $manager.TetheringOperationalState
Write-Output $status
`

// Controller manages the Windows Mobile Hotspot via PowerShell.
type Controller struct {
	mu    sync.Mutex
	state State
}

// New creates a new Controller with initial state "off".
func New() *Controller {
	return &Controller{state: StateOff}
}

// Start enables the hotspot with the given SSID and passphrase.
func (c *Controller) Start(ssid, passphrase string) error {
	c.mu.Lock()
	c.state = StateTransitioning
	c.mu.Unlock()

	script := fmt.Sprintf(psStart, ssid, passphrase)
	err := runPS(script)

	c.mu.Lock()
	if err != nil {
		c.state = StateOff
	} else {
		c.state = StateOn
	}
	c.mu.Unlock()
	return err
}

// Stop disables the hotspot.
func (c *Controller) Stop() error {
	c.mu.Lock()
	c.state = StateTransitioning
	c.mu.Unlock()

	err := runPS(psStop)

	c.mu.Lock()
	if err != nil {
		c.state = StateOn // assume still on if stop failed
	} else {
		c.state = StateOff
	}
	c.mu.Unlock()
	return err
}

// Status returns the current hotspot state.
func (c *Controller) Status() State {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.state
}

// RefreshStatus queries Windows for the actual tetering state.
func (c *Controller) RefreshStatus() State {
	out, err := exec.Command("powershell",
		"-NoProfile", "-NonInteractive", "-Command", psStatus,
	).Output()
	if err != nil {
		return c.Status()
	}
	s := strings.TrimSpace(string(out))
	c.mu.Lock()
	defer c.mu.Unlock()
	switch s {
	case "On", "1":
		c.state = StateOn
	case "Off", "0":
		c.state = StateOff
	default:
		c.state = StateTransitioning
	}
	return c.state
}

func runPS(script string) error {
	out, err := exec.Command("powershell",
		"-NoProfile", "-NonInteractive", "-Command", script,
	).CombinedOutput()
	if err != nil || !strings.Contains(string(out), "OK") {
		return fmt.Errorf("hotspot PS error: %v — %s", err, out)
	}
	return nil
}
