#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Remove the TRelay-S3-Controller Windows-side static USB network configuration.

.DESCRIPTION
    Removes the TRelay-S3-Controller host route and firewall rule, then returns
    the MicroPython USB NCM adapter to DHCP for both IPv4 addressing and DNS.
#>

[CmdletBinding()]
param(
    [string]$InterfaceAlias,
    [string]$InterfaceDescriptionPattern = "*MicroPython USB Network*",
    [string]$DeviceAddress = "172.31.77.1",
    [string]$FirewallRuleName = "TRelay-S3-Controller USB NCM Allow"
)

$ErrorActionPreference = "Stop"

function Get-ControllerAdapter {
    if ($InterfaceAlias) {
        return Get-NetAdapter -Name $InterfaceAlias -ErrorAction Stop
    }

    $matches = @(
        Get-NetAdapter -ErrorAction Stop |
            Where-Object { $_.InterfaceDescription -like $InterfaceDescriptionPattern }
    )
    if ($matches.Count -eq 0) {
        throw "No USB NCM adapter matched '$InterfaceDescriptionPattern'."
    }
    if ($matches.Count -gt 1) {
        $names = ($matches | ForEach-Object Name) -join ", "
        throw "More than one USB NCM adapter matched: $names. Re-run with -InterfaceAlias '<name>'."
    }
    return $matches[0]
}

function Invoke-NetshChecked {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    & netsh.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "netsh.exe failed with exit code $LASTEXITCODE"
    }
}

$adapter = Get-ControllerAdapter
$alias = $adapter.Name
$ifIndex = $adapter.ifIndex

Write-Host "Restoring DHCP on $alias..." -ForegroundColor Cyan

Get-NetRoute -DestinationPrefix "$DeviceAddress/32" -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue

Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue

Invoke-NetshChecked -Arguments @(
    "interface", "ipv4", "set", "address",
    "name=$alias", "source=dhcp", "store=persistent"
)
Invoke-NetshChecked -Arguments @(
    "interface", "ipv4", "set", "dnsservers",
    "name=$alias", "source=dhcp"
)

Get-NetAdapter -Name $alias | Disable-NetAdapter -Confirm:$false
Start-Sleep -Seconds 2
Get-NetAdapter -Name $alias | Enable-NetAdapter -Confirm:$false

Write-Host "DHCP restored. Current IPv4 state:" -ForegroundColor Green
Start-Sleep -Seconds 2
Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Format-Table IPAddress,PrefixLength,AddressState,PrefixOrigin
