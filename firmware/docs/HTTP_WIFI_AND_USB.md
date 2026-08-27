# HTTP over Wi-Fi and USB CDC-NCM

TRelay-S3-Controller exposes the same Microdot HTTP server over every available network interface:

- Wi-Fi station interface
- optional USB CDC-NCM interface (`network.USBD_NCM`)

Microdot binds to:

```python
await app.start_server(
    host="0.0.0.0",
    port=80,
    debug=True
)
```

Binding to `0.0.0.0` lets the same listening socket accept traffic addressed to either local interface.

## Startup behavior

1. Initialize USB CDC-NCM when the installed runtime supports it.
2. Attempt the configured Wi-Fi connection.
3. Start Microdot if at least one interface is available.
4. Use Wi-Fi for Internet-dependent NTP/weather operations.
5. Continue serving HTTP over USB if Wi-Fi is unavailable.

If `network.USBD_NCM` is not available, the application continues as a Wi-Fi-only relay controller.

## USB network

With the project's custom MicroPython runtime installed, the USB network uses:

```text
Controller: 172.31.77.1/24
Windows:    172.31.77.2/24
Gateway:    none
DNS:        none
```

Configure the Windows host from an Administrator PowerShell window with:

```powershell
.\firmware\tools\configure_controller_usb.ps1
```

## Status API

`/api/status` retains the existing top-level `ip` value for compatibility and also reports both network interfaces:

```json
{
  "network": {
    "wifi": {
      "available": true,
      "connected": true,
      "ip": "192.168.1.50"
    },
    "usb": {
      "available": true,
      "connected": true,
      "active": true,
      "ip": "172.31.77.1"
    }
  }
}
```

The top-level `ip` prefers the Wi-Fi address and falls back to the USB address.

## HTTP URLs

At boot the device prints separate Wi-Fi and USB URLs when addresses are available, for example:

```text
Wi-Fi Web UI:
    http://192.168.1.50/

USB Web UI:
    http://172.31.77.1/
```

The low-level diagnostic listener is available on port `8081` and bypasses Microdot:

```text
http://172.31.77.1:8081/
```
