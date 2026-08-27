param(
    [Parameter(Mandatory=$true)]
    [string]$ControllerIP
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=============================================="
Write-Host "LilyGo T-Relay-S3 USB NCM Windows Diagnostics"
Write-Host "=============================================="
Write-Host ""

$adapters = Get-NetAdapter -IncludeHidden |
    Where-Object {
        $_.InterfaceDescription -match "MicroPython|USB Network|NCM|Espressif"
    } |
    Sort-Object ifIndex

if (-not $adapters) {
    Write-Host "ERROR: No MicroPython / USB NCM adapter was found." -ForegroundColor Red
    exit 1
}

Write-Host "Candidate USB network adapters:"
$adapters |
    Format-Table Name, ifIndex, Status, MacAddress, LinkSpeed, InterfaceDescription -AutoSize

foreach ($adapter in $adapters) {
    Write-Host ""
    Write-Host "----------------------------------------------"
    Write-Host ("Adapter: {0}   ifIndex: {1}" -f $adapter.Name, $adapter.ifIndex)
    Write-Host "----------------------------------------------"

    $ipv4 = Get-NetIPAddress `
        -InterfaceIndex $adapter.ifIndex `
        -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "IPv4 addresses:"
    if ($ipv4) {
        $ipv4 |
            Format-Table IPAddress, PrefixLength, AddressState, PrefixOrigin, SuffixOrigin -AutoSize
    }
    else {
        Write-Host "(none)"
    }

    Write-Host ""
    Write-Host "IP configuration:"
    Get-NetIPConfiguration `
        -InterfaceIndex $adapter.ifIndex |
        Format-List InterfaceAlias, InterfaceIndex, InterfaceDescription, IPv4Address, IPv4DefaultGateway, DNSServer

    Write-Host ""
    Write-Host "Controller address supplied: $ControllerIP"

    Write-Host ""
    Write-Host "Adapter statistics BEFORE tests:"
    $before = Get-NetAdapterStatistics -Name $adapter.Name
    $before |
        Format-List ReceivedBytes, ReceivedUnicastPackets, ReceivedBroadcastPackets, SentBytes, SentUnicastPackets, SentBroadcastPackets

    Write-Host ""
    Write-Host "Route Windows would use for $ControllerIP :"
    try {
        Find-NetRoute -RemoteIPAddress $ControllerIP |
            Format-List InterfaceAlias, InterfaceIndex, DestinationPrefix, NextHop, RouteMetric, InterfaceMetric
    }
    catch {
        Write-Host ("Find-NetRoute failed: {0}" -f $_.Exception.Message)
    }

    Write-Host ""
    Write-Host "Clearing stale neighbor entry for $ControllerIP on this adapter..."
    try {
        Remove-NetNeighbor `
            -InterfaceIndex $adapter.ifIndex `
            -IPAddress $ControllerIP `
            -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
    catch {
    }

    Write-Host ""
    Write-Host "PING TEST:"
    ping.exe -n 3 $ControllerIP

    Write-Host ""
    Write-Host "TCP PORT 8081 TEST:"
    Test-NetConnection `
        -ComputerName $ControllerIP `
        -Port 8081 `
        -InformationLevel Detailed

    Write-Host ""
    Write-Host "TCP PORT 80 TEST:"
    Test-NetConnection `
        -ComputerName $ControllerIP `
        -Port 80 `
        -InformationLevel Detailed

    Write-Host ""
    Write-Host "Neighbor / ARP state:"
    Get-NetNeighbor `
        -InterfaceIndex $adapter.ifIndex `
        -IPAddress $ControllerIP `
        -ErrorAction SilentlyContinue |
        Format-Table ifIndex, IPAddress, LinkLayerAddress, State -AutoSize

    Write-Host ""
    Write-Host "Adapter statistics AFTER tests:"
    $after = Get-NetAdapterStatistics -Name $adapter.Name
    $after |
        Format-List ReceivedBytes, ReceivedUnicastPackets, ReceivedBroadcastPackets, SentBytes, SentUnicastPackets, SentBroadcastPackets

    Write-Host ""
    Write-Host "Packet deltas caused by the tests:"
    [pscustomobject]@{
        SentBytesDelta       = [int64]$after.SentBytes - [int64]$before.SentBytes
        ReceivedBytesDelta   = [int64]$after.ReceivedBytes - [int64]$before.ReceivedBytes
        SentUnicastDelta     = [int64]$after.SentUnicastPackets - [int64]$before.SentUnicastPackets
        ReceivedUnicastDelta = [int64]$after.ReceivedUnicastPackets - [int64]$before.ReceivedUnicastPackets
    } | Format-List
}

Write-Host ""
Write-Host "=============================================="
Write-Host "Interpretation"
Write-Host "=============================================="
Write-Host ""
Write-Host "TRelay-S3-Controller normally uses 172.31.77.1/24 on the USB NCM interface."
Write-Host "Use the 'USB IPv4:' value printed by TRelay-S3-Controller as -ControllerIP."
Write-Host ""
Write-Host "If the adapter is Disconnected / 0 bps, inspect the ESP32 NCM state:"
Write-Host ""
Write-Host "  import network"
Write-Host "  ncm = network.USBD_NCM()"
Write-Host "  print(ncm.active(), ncm.isconnected(), ncm.status(), ncm.ifconfig())"
Write-Host ""
