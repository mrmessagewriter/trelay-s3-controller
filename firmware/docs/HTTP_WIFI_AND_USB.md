# HTTP over Wi-Fi and USB CDC-NCM

The Sprinklers1 application now exposes the same Microdot HTTP server over
both network interfaces:

- Wi-Fi station interface
- USB CDC-NCM interface (`network.USBD_NCM`)

Microdot continues to bind to:

```python
await app.start_server(
    host="0.0.0.0",
    port=80,
    debug=False
)
```

Binding to `0.0.0.0` is important because it lets the same listening socket
accept traffic addressed to either local interface.

## Startup behavior

1. Initialize USB CDC-NCM.
2. Attempt the configured Wi-Fi connection.
3. Start Microdot if either interface is available.
4. Use Wi-Fi for Internet-dependent NTP/weather operations.
5. Continue serving HTTP over USB if Wi-Fi is unavailable.

The USB host does not need to be connected before Microdot starts. The USB
network interface can enumerate later and begin carrying HTTP traffic while
the server remains running.

## Status API

`/api/status` retains the existing top-level `ip` value for compatibility and
adds:

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
      "ip": "169.254.x.1"
    }
  }
}
```

The top-level `ip` prefers the Wi-Fi address and falls back to the USB address.

## HTTP URLs

At boot the device prints separate Wi-Fi and USB URLs when addresses are
available, for example:

```text
Wi-Fi Web UI:
    http://192.168.1.50/

USB Web UI:
    http://169.254.x.1/
```
