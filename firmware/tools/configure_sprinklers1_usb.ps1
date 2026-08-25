#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configure the Sprinklers1 MicroPython USB-NCM adapter for a fixed private LAN.

.DESCRIPTION
    Configures only the Sprinklers1/MicroPython USB NCM adapter:

      ESP32:   172.31.77.1/24
      Windows: 172.31.77.2/24
      Gateway: none
      DNS:     none

    It also marks the USB network Private, adds a persistent on-link /32 route
    to the controller, and creates a narrowly scoped outbound Windows Firewall
    allow rule for that controller on this USB interface.

    Normal Internet traffic continues to use the machine's normal default route
    (including NordVPN/NordLynx when connected).
#>

[CmdletBinding()]
param(
    [string]$InterfaceAlias,
    [string]$InterfaceDescriptionPattern = "*MicroPython USB Network*",
    [string]$DeviceAddress = "172.31.77.1",
    [string]$HostAddress = "172.31.77.2",
    [string]$Netmask = "255.255.255.0",
    [int]$PrefixLength = 24,
    [string]$FirewallRuleName = "Sprinklers1 USB NCM Allow"
)

$ErrorActionPreference = "Stop"

function Get-SprinklersAdapter {
    if ($InterfaceAlias) {
        $adapter = Get-NetAdapter -Name $InterfaceAlias -ErrorAction Stop
        return $adapter
    }

    $matches = @(
        Get-NetAdapter -ErrorAction Stop |
            Where-Object { $_.InterfaceDescription -like $InterfaceDescriptionPattern }
    )

    if ($matches.Count -eq 0) {
        throw "No USB NCM adapter matched '$InterfaceDescriptionPattern'. Connect Sprinklers1 and try again."
    }
    if ($matches.Count -gt 1) {
        $names = ($matches | ForEach-Object Name) -join ", "
        throw "More than one USB NCM adapter matched: $names. Re-run with -InterfaceAlias '<name>'."
    }
    return $matches[0]
}

function Invoke-NetshChecked {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)

    Write-Verbose ("netsh.exe " + ($Arguments -join " "))
    & netsh.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "netsh.exe failed with exit code $LASTEXITCODE"
    }
}

$adapter = Get-SprinklersAdapter
$alias = $adapter.Name
$ifIndex = $adapter.ifIndex

Write-Host "Sprinklers1 USB adapter:" -ForegroundColor Cyan
$adapter | Format-List Name,ifIndex,Status,MacAddress,LinkSpeed,InterfaceDescription

Write-Host "Configuring $alias as $HostAddress/$PrefixLength with no gateway..." -ForegroundColor Cyan

# Use netsh for the address itself because it is supported on Windows 10/11 and
# reliably replaces stale DHCP/APIPA/static state on an existing adapter.
Invoke-NetshChecked -Arguments @(
    "interface", "ipv4", "set", "address",
    "name=$alias", "source=static", "address=$HostAddress",
    "mask=$Netmask", "gateway=none", "store=persistent"
)

# This point-to-point USB network must never supply DNS.
Invoke-NetshChecked -Arguments @(
    "interface", "ipv4", "set", "dnsservers",
    "name=$alias", "source=static", "address=none",
    "register=none", "validate=no"
)

# Restart through the adapter object for compatibility with Windows versions
# where Disable-NetAdapter/Enable-NetAdapter do not expose -InterfaceIndex.
Get-NetAdapter -Name $alias | Disable-NetAdapter -Confirm:$false
Start-Sleep -Seconds 2
Get-NetAdapter -Name $alias | Enable-NetAdapter -Confirm:$false

# Wait briefly for the NCM carrier to return.
$deadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 500
    $adapter = Get-NetAdapter -Name $alias
} while ($adapter.Status -ne "Up" -and (Get-Date) -lt $deadline)

if ($adapter.Status -ne "Up") {
    Write-Warning "The adapter did not return to Up state within 15 seconds. Current status: $($adapter.Status)"
}

# Mark this directly attached controller network as Private when Windows has
# created a connection profile for it.
$profile = Get-NetConnectionProfile -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue
if ($null -ne $profile) {
    $profile | Set-NetConnectionProfile -NetworkCategory Private
} else {
    Write-Warning "Windows has not created a connection profile yet; NetworkCategory was not changed."
}

# The /24 connected route is created automatically by the static address. Add a
# host-specific /32 as an explicit preference for Sprinklers1. New-NetRoute
# saves routes in active and persistent stores by default.
Get-NetRoute -DestinationPrefix "$DeviceAddress/32" -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue

New-NetRoute `
    -DestinationPrefix "$DeviceAddress/32" `
    -InterfaceIndex $ifIndex `
    -NextHop "0.0.0.0" `
    -RouteMetric 1 | Out-Null

# Replace our own previous firewall rule. It permits only outbound traffic to
# this one controller and only through this USB interface.
Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName $FirewallRuleName `
    -Description "Allow local access to Sprinklers1 at $DeviceAddress through $alias only." `
    -Direction Outbound `
    -Action Allow `
    -InterfaceAlias $alias `
    -RemoteAddress $DeviceAddress `
    -Profile Any | Out-Null

Write-Host ""
Write-Host "Final USB configuration:" -ForegroundColor Green
Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Format-Table IPAddress,PrefixLength,AddressState,PrefixOrigin

Get-NetRoute -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Sort-Object PrefixLength -Descending |
    Format-Table DestinationPrefix,NextHop,RouteMetric,State

Write-Host "Controller URLs:" -ForegroundColor Green
Write-Host "  http://$DeviceAddress/"
Write-Host "  http://$DeviceAddress/api/status"
Write-Host "  http://$DeviceAddress`:8081/"
Write-Host ""
Write-Host "NordVPN: keep 'Stay invisible on LAN' OFF. The USB adapter has no gateway, so it cannot become the Internet path." -ForegroundColor Yellow

# Informational tests only; installation remains successful if the application
# is not currently listening on one of these ports.
foreach ($port in @(80, 8081)) {
    try {
        $ok = Test-NetConnection -ComputerName $DeviceAddress -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
        Write-Host ("TCP {0}: {1}" -f $port, $(if ($ok) { "reachable" } else { "not reachable" }))
    } catch {
        Write-Host "TCP $port: test unavailable"
    }
}
