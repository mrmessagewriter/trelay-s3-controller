# ============================================================
# LilyGo T-Relay ESP32-S3
# MicroPython + Microdot
#
# Dual-network HTTP build:
#   - Connects to an EXISTING Wi-Fi network when available
#   - Enables USB CDC-NCM networking when supported by the runtime
#   - Does NOT create a Wi-Fi access point
#   - Serves the same HTTP UI/API over Wi-Fi and USB
#   - Controls six relays through the 74HC595
#   - Provides REST API
#   - Serves:
#       /static/index.html
#       /static/setup.html
#
# Required files on ESP32:
#
#   /main.py
#   /config.json        Device configuration only
#   /events.json        Persistent events + event log (runtime data)
#   /static/index.html
#   /static/setup.html
#   Microdot installation
#
# ============================================================

from machine import Pin, reset
import network
import time
import gc
import json
import os


# ============================================================
# CONSTANTS
# ============================================================

CONFIG_FILE = "/config.json"
WEB_PORT = 80
WIFI_CONNECT_TIMEOUT = 30
DEFAULT_NTP_SERVER = "pool.ntp.org"
DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_NTP_SYNC_INTERVAL_HOURS = 12
DEFAULT_WEATHER_REFRESH_MINUTES = 30


# ============================================================
# LILYGO T-RELAY ESP32-S3 HARDWARE
#
# ESP32 GPIO -> 74HC595
#
# GPIO 7 = DATA
# GPIO 5 = CLOCK
# GPIO 6 = LATCH
# GPIO 4 = OUTPUT ENABLE
#
# 74HC595 outputs:
#
# bit 0 = Relay 1
# bit 1 = Relay 2
# bit 2 = Relay 3
# bit 3 = Relay 4
# bit 4 = Relay 5
# bit 5 = Relay 6
# bit 6 = Green LED
# bit 7 = Red LED
# ============================================================

DATA_PIN = 7
CLOCK_PIN = 5
LATCH_PIN = 6
ENABLE_PIN = 4


data = Pin(DATA_PIN, Pin.OUT, value=0)
clock = Pin(CLOCK_PIN, Pin.OUT, value=0)
latch = Pin(LATCH_PIN, Pin.OUT, value=0)
enable = Pin(ENABLE_PIN, Pin.OUT, value=1)


output_state = 0x00

config = None
station = None
usb_ncm = None

app = None
send_file = None

time_synchronized = False
last_ntp_sync = 0
weather_service = None
events_service = None
firmware_info = None


# ============================================================
# DEFAULT CONFIG
# ============================================================

def default_config():

    return {
        "device_name": "TRelay-S3-Controller",

        "wifi": {
            "ssid": "",
            "password": ""
        },

        "time": {
            "ntp_server": DEFAULT_NTP_SERVER,
            "timezone": DEFAULT_TIMEZONE,
            "sync_interval_hours": DEFAULT_NTP_SYNC_INTERVAL_HOURS
        },

        "weather": {
            "enabled": False,
            "zip_code": "",
            "country_code": "US",
            "latitude": 0.0,
            "longitude": 0.0,
            "resolved_name": "",
            "refresh_minutes": DEFAULT_WEATHER_REFRESH_MINUTES
        },

        "event_blocks": {
            "rain_threshold_in": 0.25,
            "rain_lookback_days": 2,
            "wind_max_mph": 15.0
        },

        "relays": [
            {"name": "Relay 1"},
            {"name": "Relay 2"},
            {"name": "Relay 3"},
            {"name": "Relay 4"},
            {"name": "Relay 5"},
            {"name": "Relay 6"}
        ]
    }


# ============================================================
# CONFIGURATION
# ============================================================

def load_config():

    global config

    try:

        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

        print("Configuration loaded.")

    except Exception as e:

        print("Unable to load config.json:", repr(e))
        config = default_config()


    if "device_name" not in config:
        config["device_name"] = "TRelay-S3-Controller"


    if "wifi" not in config:

        config["wifi"] = {
            "ssid": "",
            "password": ""
        }


    if "ssid" not in config["wifi"]:
        config["wifi"]["ssid"] = ""


    if "password" not in config["wifi"]:
        config["wifi"]["password"] = ""


    if "time" not in config:

        config["time"] = {
            "ntp_server": DEFAULT_NTP_SERVER,
            "timezone": DEFAULT_TIMEZONE,
            "sync_interval_hours": DEFAULT_NTP_SYNC_INTERVAL_HOURS
        }

    if "ntp_server" not in config["time"]:
        config["time"]["ntp_server"] = DEFAULT_NTP_SERVER

    if "timezone" not in config["time"]:
        config["time"]["timezone"] = DEFAULT_TIMEZONE

    if "sync_interval_hours" not in config["time"]:
        config["time"]["sync_interval_hours"] = DEFAULT_NTP_SYNC_INTERVAL_HOURS

    if "weather" not in config:
        config["weather"] = {
            "enabled": False,
            "zip_code": "",
            "country_code": "US",
            "latitude": 0.0,
            "longitude": 0.0,
            "resolved_name": "",
            "refresh_minutes": DEFAULT_WEATHER_REFRESH_MINUTES
        }

    config["weather"].setdefault(
        "enabled",
        False
    )

    config["weather"].setdefault(
        "zip_code",
        ""
    )

    config["weather"].setdefault(
        "country_code",
        "US"
    )

    config["weather"].setdefault(
        "resolved_name",
        ""
    )

    config["weather"].setdefault(
        "latitude",
        0.0
    )

    config["weather"].setdefault(
        "longitude",
        0.0
    )

    config["weather"].setdefault(
        "refresh_minutes",
        DEFAULT_WEATHER_REFRESH_MINUTES
    )

    if "event_blocks" not in config:

        config["event_blocks"] = {
            "rain_threshold_in": 0.25,
            "rain_lookback_days": 2,
            "wind_max_mph": 15.0
        }

    config["event_blocks"].setdefault(
        "rain_threshold_in",
        0.25
    )

    config["event_blocks"].setdefault(
        "rain_lookback_days",
        2
    )

    config["event_blocks"].setdefault(
        "wind_max_mph",
        15.0
    )

    if "relays" not in config:

        config["relays"] = (
            default_config()["relays"]
        )


    while len(config["relays"]) < 6:

        number = len(config["relays"]) + 1

        config["relays"].append({
            "name": "Relay {}".format(number)
        })


    if len(config["relays"]) > 6:
        config["relays"] = config["relays"][:6]


    return config


def save_config():

    temp_file = CONFIG_FILE + ".tmp"

    try:

        with open(temp_file, "w") as f:
            json.dump(config, f)


        try:
            os.remove(CONFIG_FILE)
        except:
            pass


        os.rename(
            temp_file,
            CONFIG_FILE
        )

        print("Configuration saved.")

        return True


    except Exception as e:

        print(
            "Configuration save failed:",
            repr(e)
        )

        return False


# ============================================================
# 74HC595 DRIVER
# ============================================================

def shift_out(value):

    latch.value(0)

    for bit in range(7, -1, -1):

        clock.value(0)

        if value & (1 << bit):
            data.value(1)
        else:
            data.value(0)

        clock.value(1)


    clock.value(0)

    latch.value(1)
    latch.value(0)


def update_outputs():

    shift_out(output_state)


# ============================================================
# RELAY CONTROL
# ============================================================

def valid_relay(number):

    return 1 <= number <= 6


def relay_get(number):

    if not valid_relay(number):

        raise ValueError(
            "Relay must be 1 through 6"
        )


    return bool(
        output_state &
        (1 << (number - 1))
    )


def relay_on(number):

    global output_state

    if not valid_relay(number):

        raise ValueError(
            "Relay must be 1 through 6"
        )


    output_state |= (
        1 << (number - 1)
    )

    update_outputs()

    print("Relay", number, "ON")


def relay_off(number):

    global output_state

    if not valid_relay(number):

        raise ValueError(
            "Relay must be 1 through 6"
        )


    output_state &= ~(
        1 << (number - 1)
    )

    update_outputs()

    print("Relay", number, "OFF")


def relay_toggle(number):

    global output_state

    if not valid_relay(number):

        raise ValueError(
            "Relay must be 1 through 6"
        )


    output_state ^= (
        1 << (number - 1)
    )

    update_outputs()

    print(
        "Relay",
        number,
        "ON" if relay_get(number) else "OFF"
    )


def relay_set(number, state):

    if state:
        relay_on(number)
    else:
        relay_off(number)


def all_relays_on():

    global output_state

    output_state |= 0x3F

    update_outputs()

    print("All relays ON")


def all_relays_off():

    global output_state

    output_state &= ~0x3F

    update_outputs()

    print("All relays OFF")


# ============================================================
# ONBOARD LEDs
# ============================================================

def green_led(state):

    global output_state

    if state:
        output_state |= 0x40
    else:
        output_state &= ~0x40

    update_outputs()


def red_led(state):

    global output_state

    if state:
        output_state |= 0x80
    else:
        output_state &= ~0x80

    update_outputs()


# ============================================================
# RELAY INITIALIZATION
# ============================================================

def initialize_relays():

    global output_state

    enable.value(1)

    output_state = 0x00

    shift_out(0x00)

    enable.value(0)

    print("Relay hardware initialized.")
    print("All relays OFF.")

def test_relays(delay_ms=750):
    print()
    print("============================")
    print("RELAY STARTUP TEST")
    print("============================")

    # Start with everything off.
    all_relays_off()
    time.sleep_ms(delay_ms)

    # Test relays 1 through 6 individually.
    for number in range(1, 7):

        print("Testing relay", number)

        relay_on(number)
        time.sleep_ms(delay_ms)

        relay_off(number)
        time.sleep_ms(delay_ms)

    # Make absolutely sure everything is off afterward.
    all_relays_off()

    print()
    print("Relay startup test complete.")
    print()

# ============================================================
# USB CDC-NCM NETWORK
# ============================================================

def _interface_ipv4(interface):
    """Return an interface IPv4 address without a prefix length."""

    if interface is None:
        return ""

    try:
        value = interface.ipconfig("addr4")

        if isinstance(value, str):
            if "/" in value:
                return value.split("/")[0]

            return value

        # Some ports may return a tuple/list of addresses.
        if isinstance(value, (tuple, list)) and value:
            value = value[0]

            if isinstance(value, str):
                if "/" in value:
                    return value.split("/")[0]

                return value

    except Exception:
        pass

    try:
        value = interface.ifconfig()[0]

        if isinstance(value, str):
            return value

    except Exception:
        pass

    return ""


def initialize_usb_network():
    """Initialize MicroPython USB CDC-NCM networking when available.

    The NCM interface does not need a connected host before Microdot starts.
    The HTTP listener binds to 0.0.0.0 and will accept USB traffic whenever
    the host enumerates/configures the USB network adapter.
    """

    global usb_ncm

    print()
    print("============================")
    print("USB CDC-NCM NETWORK")
    print("============================")

    try:
        ncm_class = network.USBD_NCM

    except AttributeError:
        print()
        print(
            "USB NCM is not available in this MicroPython runtime."
        )
        usb_ncm = None
        return False

    try:
        usb_ncm = ncm_class()

        # The interface is normally active from boot, but make the intended
        # application state explicit.
        if not usb_ncm.active():
            usb_ncm.active(True)

        print()
        print("USB NCM active:", usb_ncm.active())

        try:
            print(
                "USB host connected:",
                usb_ncm.isconnected()
            )
        except Exception:
            pass

        address = _interface_ipv4(usb_ncm)

        if address:
            print("USB IPv4:", address)
        else:
            print(
                "USB IPv4 is not available yet; "
                "the host may not have enumerated the NCM interface."
            )

        return bool(usb_ncm.active())

    except Exception as e:
        print()
        print(
            "Unable to initialize USB NCM:",
            repr(e)
        )

        usb_ncm = None
        return False


def usb_ip():
    return _interface_ipv4(usb_ncm)


def usb_is_connected():

    if usb_ncm is None:
        return False

    try:
        return bool(usb_ncm.isconnected())
    except Exception:
        return False


# ============================================================
# WIFI
# ============================================================

def get_station_interface():

    # Current MicroPython ESP32 builds commonly support
    # WLAN(IF_STA). Older builds use STA_IF.

    try:

        return network.WLAN(
            network.WLAN.IF_STA
        )

    except AttributeError:

        return network.WLAN(
            network.STA_IF
        )


def connect_wifi():

    global station


    ssid = config["wifi"].get(
        "ssid",
        ""
    )

    password = config["wifi"].get(
        "password",
        ""
    )


    if not ssid:

        print()
        print("ERROR: No Wi-Fi SSID configured.")
        return False


    gc.collect()

    print()
    print("============================")
    print("CONNECTING TO EXISTING WIFI")
    print("============================")

    print()
    print("SSID:", repr(ssid))
    print("SSID length:", len(ssid))
    print("Password length:", len(password))
    print("Free memory:", gc.mem_free())


    try:

        station = get_station_interface()

    except Exception as e:

        print(
            "Unable to create WLAN station:",
            repr(e)
        )

        return False


    print("Station interface created.")


    try:

        station.active(True)

    except Exception as e:

        print(
            "Unable to activate Wi-Fi:",
            repr(e)
        )

        return False


    # Give ESP-IDF a little time to finish radio startup.

    time.sleep_ms(1000)


    print(
        "Station active:",
        station.active()
    )


    try:

        print(
            "Status before connect:",
            station.status()
        )

    except:
        pass


    # --------------------------------------------------------
    # Scan and report target network.
    #
    # This is diagnostic only. A scan failure does not prevent
    # us from attempting a connection.
    # --------------------------------------------------------

    try:

        print()
        print("Scanning for target network...")

        networks = station.scan()

        found = False


        for item in networks:

            raw_ssid = item[0]

            try:
                network_name = raw_ssid.decode("utf-8")
            except:
                network_name = str(raw_ssid)


            if network_name == ssid:

                found = True

                print("Target network found:")
                print("  SSID:", repr(network_name))
                print("  Channel:", item[2])
                print("  RSSI:", item[3])
                print("  Security:", item[4])
                print("  Hidden:", item[5])

                break


        print(
            "Configured SSID found:",
            found
        )


        networks = None
        gc.collect()


    except Exception as e:

        print(
            "Wi-Fi scan warning:",
            repr(e)
        )


    print()
    print(
        "Connecting to:",
        repr(ssid)
    )


    try:

        station.connect(
            ssid,
            password
        )

    except Exception as e:

        print()
        print(
            "WiFi connect() failed:",
            repr(e)
        )

        try:
            print(
                "Station status:",
                station.status()
            )
        except:
            pass

        return False


    print("connect() accepted.")


    # --------------------------------------------------------
    # Wait for connection / DHCP
    # --------------------------------------------------------

    started = time.ticks_ms()

    last_status = None


    while not station.isconnected():

        try:

            status = station.status()


            if status != last_status:

                print(
                    "Wi-Fi status:",
                    status
                )

                last_status = status

        except:
            status = None


        elapsed = time.ticks_diff(
            time.ticks_ms(),
            started
        )


        if elapsed >= (
            WIFI_CONNECT_TIMEOUT * 1000
        ):

            print()
            print(
                "Wi-Fi connection timed out."
            )

            try:
                print(
                    "Final status:",
                    station.status()
                )
            except:
                pass

            return False


        time.sleep_ms(500)


    print()
    print("============================")
    print("WIFI CONNECTED")
    print("============================")


    try:

        print(
            "IPv4:",
            station.ipconfig("addr4")
        )

    except:

        try:

            print(
                "Network config:",
                station.ifconfig()
            )

        except Exception as e:

            print(
                "Unable to read IP configuration:",
                repr(e)
            )


    print(
        "Free memory after Wi-Fi:",
        gc.mem_free()
    )


    return True


# ============================================================
# NETWORK STATUS / ADDRESSES
# ============================================================

def wifi_ip():
    return _interface_ipv4(station)


def wifi_is_connected():

    if station is None:
        return False

    try:
        return bool(station.isconnected())
    except Exception:
        return False


def current_ip():
    """Return the preferred address for backward-compatible API/UI use.

    Prefer Wi-Fi when connected because it is normally reachable from the
    LAN. Fall back to USB so the UI/API still has a useful address when Wi-Fi
    is unavailable.
    """

    address = wifi_ip()

    if address:
        return address

    return usb_ip()


def get_network_status():

    return {
        "wifi": {
            "available": station is not None,
            "connected": wifi_is_connected(),
            "ip": wifi_ip()
        },

        "usb": {
            "available": usb_ncm is not None,
            "connected": usb_is_connected(),
            "active": (
                bool(usb_ncm.active())
                if usb_ncm is not None
                else False
            ),
            "ip": usb_ip()
        }
    }


# ============================================================
# TIME / NTP
# ============================================================

def _weekday_sunday_zero(year, month, day):
    """Return weekday where Sunday=0, Monday=1, ... Saturday=6."""

    offsets = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)

    y = year

    if month < 3:
        y -= 1

    return (
        y + y // 4 - y // 100 + y // 400 +
        offsets[month - 1] + day
    ) % 7


def _nth_sunday(year, month, nth):

    first_weekday = _weekday_sunday_zero(
        year,
        month,
        1
    )

    first_sunday = 1 + ((7 - first_weekday) % 7)

    return first_sunday + ((nth - 1) * 7)


def _pacific_offset_seconds(epoch):
    """Return Pacific UTC offset and abbreviation for an epoch."""

    utc = time.gmtime(epoch)
    year = utc[0]

    # Since 2007, US DST begins on the second Sunday in March
    # at 02:00 PST (10:00 UTC), and ends on the first Sunday
    # in November at 02:00 PDT (09:00 UTC).

    dst_start_day = _nth_sunday(year, 3, 2)
    dst_end_day = _nth_sunday(year, 11, 1)

    dst_start = time.mktime((
        year, 3, dst_start_day,
        10, 0, 0, 0, 0
    ))

    dst_end = time.mktime((
        year, 11, dst_end_day,
        9, 0, 0, 0, 0
    ))

    if dst_start <= epoch < dst_end:
        return -7 * 3600, "PDT", True

    return -8 * 3600, "PST", False


def timezone_offset_seconds(epoch=None):

    if epoch is None:
        epoch = time.time()

    timezone = config.get(
        "time",
        {}
    ).get(
        "timezone",
        DEFAULT_TIMEZONE
    )

    if timezone in (
        "America/Los_Angeles",
        "US/Pacific",
        "Pacific"
    ):
        return _pacific_offset_seconds(epoch)

    return 0, "UTC", False


def format_datetime(tm):

    return (
        "%04d-%02d-%02d %02d:%02d:%02d" % (
            tm[0],
            tm[1],
            tm[2],
            tm[3],
            tm[4],
            tm[5]
        )
    )


def get_time_status():

    epoch = time.time()
    utc_tm = time.gmtime(epoch)

    offset, abbreviation, is_dst = (
        timezone_offset_seconds(epoch)
    )

    local_tm = time.gmtime(
        epoch + offset
    )

    return {
        "synchronized": time_synchronized,
        "utc": format_datetime(utc_tm),
        "local": format_datetime(local_tm),
        "timezone": config.get(
            "time",
            {}
        ).get(
            "timezone",
            DEFAULT_TIMEZONE
        ),
        "timezone_abbreviation": abbreviation,
        "utc_offset_seconds": offset,
        "dst": is_dst,
        "last_sync_epoch": last_ntp_sync
    }


def get_local_time_tuple():

    epoch = time.time()
    offset, _, _ = timezone_offset_seconds(epoch)
    return time.gmtime(epoch + offset)


def get_local_time_string():

    status = get_time_status()
    return status["local"] + " " + status["timezone_abbreviation"]


def _set_rtc_from_epoch(epoch):

    from machine import RTC

    tm = time.gmtime(epoch)

    RTC().datetime((
        tm[0],
        tm[1],
        tm[2],
        tm[6] + 1,
        tm[3],
        tm[4],
        tm[5],
        0
    ))


def _fallback_ntp_time(host, timeout=5):
    """Small NTP client used only if ntptime is unavailable."""

    import socket
    import struct

    query = bytearray(48)
    query[0] = 0x23

    address = socket.getaddrinfo(
        host,
        123
    )[0][-1]

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    try:

        sock.settimeout(timeout)
        sock.sendto(query, address)
        response = sock.recv(48)

    finally:

        sock.close()

    value = struct.unpack(
        "!I",
        response[40:44]
    )[0]

    # NTP timestamp wraps in 2036. This matches the current
    # MicroPython ntptime implementation's handling.
    minimum_ntp_timestamp = 3913056000

    if value < minimum_ntp_timestamp:
        value += 0x100000000

    epoch_year = time.gmtime(0)[0]

    if epoch_year == 2000:
        delta = 3155673600
    elif epoch_year == 1970:
        delta = 2208988800
    else:
        raise Exception(
            "Unsupported epoch: {}".format(epoch_year)
        )

    return value - delta


def sync_time():

    global time_synchronized
    global last_ntp_sync

    time_config = config.get(
        "time",
        {}
    )

    server = time_config.get(
        "ntp_server",
        DEFAULT_NTP_SERVER
    )

    print()
    print("============================")
    print("SYNCHRONIZING TIME")
    print("============================")
    print("NTP server:", server)

    try:

        try:

            import ntptime

            ntptime.host = server

            if hasattr(ntptime, "timeout"):
                ntptime.timeout = 5

            ntptime.settime()

            print("NTP synchronized using ntptime.")

        except ImportError:

            epoch = _fallback_ntp_time(
                server,
                5
            )

            _set_rtc_from_epoch(epoch)

            print("NTP synchronized using built-in fallback.")

        time_synchronized = True
        last_ntp_sync = time.time()

        status = get_time_status()

        print("UTC:", status["utc"])
        print(
            "Local:",
            status["local"],
            status["timezone_abbreviation"]
        )

        return True

    except Exception as e:

        print(
            "NTP synchronization failed:",
            repr(e)
        )

        return False


def ntp_sync_interval_seconds():

    try:
        hours = int(
            config.get("time", {}).get(
                "sync_interval_hours",
                DEFAULT_NTP_SYNC_INTERVAL_HOURS
            )
        )
    except:
        hours = DEFAULT_NTP_SYNC_INTERVAL_HOURS

    if hours < 1:
        hours = 1

    if hours > 168:
        hours = 168

    return hours * 3600


# ============================================================
# WEATHER
# ============================================================

def resolve_weather_location_from_zip():
    """
    Resolve configured ZIP/postal code once during boot.

    This function must only be called after Wi-Fi is connected.
    On success it stores latitude/longitude back into config.json.
    On failure it keeps the previously saved coordinates.
    """

    weather_config = config.get(
        "weather",
        {}
    )

    zip_code = str(
        weather_config.get(
            "zip_code",
            ""
        )
    ).strip()

    if not zip_code:

        print(
            "No ZIP code configured; using saved coordinates."
        )

        return False

    country_code = str(
        weather_config.get(
            "country_code",
            "US"
        )
    ).strip().upper()

    if not country_code:
        country_code = "US"

    print()
    print("============================")
    print("RESOLVING WEATHER LOCATION")
    print("============================")
    print("ZIP/postal code:", zip_code)
    print("Country:", country_code)

    try:

        from weather import resolve_postal_code

        result = resolve_postal_code(
            zip_code,
            country_code
        )

        weather_config["latitude"] = (
            result["latitude"]
        )

        weather_config["longitude"] = (
            result["longitude"]
        )

        weather_config["resolved_name"] = (
            result.get(
                "name",
                ""
            )
        )

        weather_config["country_code"] = (
            result.get(
                "country_code",
                country_code
            )
        )

        config["weather"] = weather_config

        # If the geocoder supplies an IANA timezone, use it
        # for the time configuration as well.
        resolved_timezone = result.get(
            "timezone",
            ""
        )

        if resolved_timezone:

            config["time"]["timezone"] = (
                resolved_timezone
            )

        if not save_config():

            print(
                "WARNING: resolved coordinates could not be saved."
            )

        print(
            "Resolved location:",
            weather_config.get(
                "resolved_name",
                ""
            )
        )

        print(
            "Latitude:",
            weather_config["latitude"]
        )

        print(
            "Longitude:",
            weather_config["longitude"]
        )

        return True

    except Exception as e:

        print(
            "ZIP lookup failed:",
            repr(e)
        )

        print(
            "Using previously saved coordinates:",
            weather_config.get(
                "latitude",
                0.0
            ),
            weather_config.get(
                "longitude",
                0.0
            )
        )

        return False


def initialize_weather():

    global weather_service

    weather_config = config.get(
        "weather",
        {}
    )

    if not weather_config.get(
        "enabled",
        False
    ):

        print("Weather service disabled.")
        weather_service = None
        return False

    try:

        latitude = float(
            weather_config.get(
                "latitude",
                0.0
            )
        )

        longitude = float(
            weather_config.get(
                "longitude",
                0.0
            )
        )

        refresh_minutes = int(
            weather_config.get(
                "refresh_minutes",
                DEFAULT_WEATHER_REFRESH_MINUTES
            )
        )

    except Exception as e:

        print(
            "Invalid weather configuration:",
            repr(e)
        )

        weather_service = None
        return False

    if latitude == 0.0 and longitude == 0.0:

        print(
            "Weather service has no location configured."
        )

        weather_service = None
        return False

    try:

        from weather import WeatherService

        weather_service = WeatherService(
            latitude,
            longitude,
            refresh_minutes
        )

        return True

    except Exception as e:

        print(
            "Unable to initialize weather service:",
            repr(e)
        )

        weather_service = None
        return False


def refresh_weather():

    if weather_service is None:
        return False

    return weather_service.refresh()


def get_weather_status():

    if weather_service is None:

        return {
            "enabled":
                config.get(
                    "weather",
                    {}
                ).get(
                    "enabled",
                    False
                ),

            "valid":
                False,

            "stale":
                True,

            "last_error":
                "Weather service not initialized",

            "current":
                {},

            "daily":
                []
        }

    status = weather_service.status()

    status["enabled"] = True

    return status


def weather_refresh_interval_seconds():

    if weather_service is None:
        return (
            DEFAULT_WEATHER_REFRESH_MINUTES *
            60
        )

    return weather_service.refresh_interval_seconds()


# ============================================================
# EVENTS
# ============================================================

def relay_name(number):

    if not valid_relay(number):
        return ""

    return config["relays"][number - 1].get(
        "name",
        "Relay {}".format(number)
    )


def relay_number_from_name(name):

    target = str(name).strip().lower()

    for index in range(6):

        current = config["relays"][index].get(
            "name",
            "Relay {}".format(index + 1)
        )

        if str(current).strip().lower() == target:
            return index + 1

    return None


def current_weather_temperature():

    status = get_weather_status()

    if (
        not status.get("valid", False)
        or status.get("stale", True)
    ):
        return None

    return status.get(
        "current",
        {}
    ).get(
        "temperature_f",
        None
    )


def current_weather_wind_mph():

    status = get_weather_status()

    if (
        not status.get("valid", False)
        or status.get("stale", True)
    ):
        return None

    return status.get(
        "current",
        {}
    ).get(
        "wind_mph",
        None
    )


def recent_weather_rain_inches():

    if weather_service is None:
        return None

    status = get_weather_status()

    if (
        not status.get("valid", False)
        or status.get("stale", True)
    ):
        return None

    days = config.get(
        "event_blocks",
        {}
    ).get(
        "rain_lookback_days",
        2
    )

    try:
        return weather_service.recent_rain_inches(
            days
        )
    except Exception as e:
        print(
            "Unable to read recent rain:",
            repr(e)
        )
        return None


def event_block_settings():

    return config.get(
        "event_blocks",
        {
            "rain_threshold_in": 0.25,
            "rain_lookback_days": 2,
            "wind_max_mph": 15.0
        }
    )


def initialize_events():

    global events_service

    try:

        from events import EventService

        events_service = EventService(
            relay_on=relay_on,
            relay_off=relay_off,
            all_relays_on=all_relays_on,
            all_relays_off=all_relays_off,
            relay_get=relay_get,
            relay_name=relay_name,
            relay_number_from_name=relay_number_from_name,
            local_time_tuple=get_local_time_tuple,
            local_time_string=get_local_time_string,
            current_temperature=current_weather_temperature,
            current_wind=current_weather_wind_mph,
            recent_rain=recent_weather_rain_inches,
            block_settings=event_block_settings,
            time_is_synchronized=lambda: time_synchronized,
        )

        print(
            "Event scheduler initialized with",
            len(events_service.list_events()),
            "event(s)."
        )

        return True

    except Exception as e:

        print(
            "Unable to initialize event scheduler:",
            repr(e)
        )

        events_service = None
        return False


def get_events_status():

    if events_service is None:
        return {
            "available": False,
            "events": []
        }

    return {
        "available": True,
        "events": events_service.list_events()
    }


def get_event_log(limit=50):

    if events_service is None:
        return []

    return events_service.recent_log(limit)


def log_manual_relay_action(
    action,
    relay_number=None,
    relay_state=None,
    all_relays=False
):

    if events_service is None:
        return

    if all_relays:

        event_name = (
            "Manual: All Relays"
        )

        detail = (
            "All relays "
            + (
                "ON"
                if relay_state
                else "OFF"
            )
        )

    else:

        relay_name = (
            config["relays"][
                relay_number - 1
            ].get(
                "name",
                "Relay {}".format(
                    relay_number
                )
            )
        )

        event_name = (
            "Manual: "
            + relay_name
        )

        detail = (
            "Relay {} ({}) {}".format(
                relay_number,
                relay_name,
                (
                    "ON"
                    if relay_state
                    else "OFF"
                )
            )
        )

    try:

        events_service.log_manual(
            action=action,
            event_name=event_name,
            detail=detail,
            relay_number=relay_number,
            relay_state=relay_state
        )

    except Exception as e:

        print(
            "Unable to log manual relay action:",
            repr(e)
        )


def get_upcoming_events(limit=3):

    if events_service is None:
        return []

    return events_service.upcoming(limit)


# ============================================================
# FIRMWARE INFORMATION
# ============================================================

def get_firmware_info():
    """
    Read firmware_info.json from the mounted firmware image.

    The value is cached after the first successful read so status
    requests do not repeatedly access the ZIP/VFS.
    """

    global firmware_info

    if firmware_info is not None:
        return firmware_info

    candidates = (
        "/firmware/firmware_info.json",
        "/firmware_info.json",
        "firmware_info.json",
    )

    for path in candidates:
        try:
            with open(path, "r") as f:
                data = json.load(f)

            firmware_info = {
                "name":
                    data.get(
                        "name",
                        "TRelay-S3-Controller"
                    ),

                "version":
                    data.get(
                        "version",
                        "unknown"
                    ),

                "date":
                    data.get(
                        "date",
                        ""
                    )
            }

            return firmware_info

        except Exception:
            pass

    firmware_info = {
        "name": "TRelay-S3-Controller",
        "version": "unknown",
        "date": ""
    }

    return firmware_info


# ============================================================
# STATUS
# ============================================================

def get_status():

    relays = []


    for index in range(6):

        number = index + 1


        relays.append({

            "relay":
                number,

            "name":
                config["relays"][index].get(
                    "name",
                    "Relay {}".format(number)
                ),

            "state":
                relay_get(number)
        })


    return {

        "device":
            config.get(
                "device_name",
                "TRelay-S3-Controller"
            ),

        "firmware":
            get_firmware_info(),

        # "ip" is kept for backward compatibility. It prefers Wi-Fi and
        # falls back to USB.
        "ip":
            current_ip(),

        "network":
            get_network_status(),

        "time":
            get_time_status(),

        "weather":
            get_weather_status(),

        "relays":
            relays
    }


# ============================================================
# DELAYED REBOOT
# ============================================================

def schedule_reboot():

    import asyncio


    async def reboot_later():

        await asyncio.sleep(1)

        reset()


    asyncio.create_task(
        reboot_later()
    )


# ============================================================
# WEB SERVER
#
# Microdot is imported after the network interfaces have been initialized.
# The server binds to 0.0.0.0, so one socket accepts HTTP over Wi-Fi and USB.
# ============================================================

def initialize_web_server():
    """Create Microdot and register all routes.

    Do not write diagnostic output here.

    On this board the USB CDC console and CDC-NCM network interface share the
    same native USB/TinyUSB device. A blocking CDC write during startup must
    never be allowed to prevent the HTTP server from reaching start_server().
    Runtime diagnostics are available through /api/status instead.
    """

    global app
    global send_file

    gc.collect()

    from microdot import Microdot
    from microdot import send_file as microdot_send_file

    send_file = microdot_send_file

    gc.collect()

    app = Microdot()

    register_routes()

    gc.collect()


# ============================================================
# WEB + REST ROUTES
# ============================================================

def static_file_path(filename):
    """Return a static asset path for ZIP/VFS or direct-filesystem runs."""

    import os

    candidates = (
        "/firmware/static/" + filename,
        "/static/" + filename,
        "static/" + filename,
    )

    for path in candidates:
        try:
            os.stat(path)
            return path
        except OSError:
            pass

    # Prefer the ZIP/VFS location in the failure message.
    return candidates[0]


def register_routes():

    # --------------------------------------------------------
    # WEB UI
    # --------------------------------------------------------

    @app.get("/")
    async def index(request):

        return send_file(
            static_file_path("index.html")
        )


    @app.get("/setup")
    async def setup(request):

        return send_file(
            static_file_path("setup.html")
        )


    @app.get("/events")
    async def events_page(request):

        return send_file(
            static_file_path("events.html")
        )


    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    @app.get("/api/status")
    async def api_status(request):

        return get_status()


    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    @app.get("/api/config")
    async def api_config(request):

        # Wi-Fi password intentionally excluded.

        return {

            "device_name":
                config.get(
                    "device_name",
                    "TRelay-S3-Controller"
                ),

            "ssid":
                config["wifi"].get(
                    "ssid",
                    ""
                ),

            "ntp_server":
                config["time"].get(
                    "ntp_server",
                    DEFAULT_NTP_SERVER
                ),

            "timezone":
                config["time"].get(
                    "timezone",
                    DEFAULT_TIMEZONE
                ),

            "sync_interval_hours":
                config["time"].get(
                    "sync_interval_hours",
                    DEFAULT_NTP_SYNC_INTERVAL_HOURS
                ),

            "weather_enabled":
                config["weather"].get(
                    "enabled",
                    False
                ),

            "weather_zip_code":
                config["weather"].get(
                    "zip_code",
                    ""
                ),

            "weather_country_code":
                config["weather"].get(
                    "country_code",
                    "US"
                ),

            "weather_resolved_name":
                config["weather"].get(
                    "resolved_name",
                    ""
                ),

            "weather_latitude":
                config["weather"].get(
                    "latitude",
                    0.0
                ),

            "weather_longitude":
                config["weather"].get(
                    "longitude",
                    0.0
                ),

            "weather_refresh_minutes":
                config["weather"].get(
                    "refresh_minutes",
                    DEFAULT_WEATHER_REFRESH_MINUTES
                ),

            "block_rain_threshold_in":
                config["event_blocks"].get(
                    "rain_threshold_in",
                    0.25
                ),

            "block_rain_lookback_days":
                config["event_blocks"].get(
                    "rain_lookback_days",
                    2
                ),

            "block_wind_max_mph":
                config["event_blocks"].get(
                    "wind_max_mph",
                    15.0
                ),

            "relays":
                config["relays"]
        }


    @app.post("/api/config")
    async def api_save_config(request):

        body = request.json


        if not body:

            return {
                "error":
                    "JSON body required"
            }, 400


        if "device_name" in body:

            device_name = str(
                body["device_name"]
            ).strip()


            if device_name:

                config["device_name"] = (
                    device_name
                )


        if "ssid" in body:

            config["wifi"]["ssid"] = str(
                body["ssid"]
            ).strip()


        if "password" in body:

            password = str(
                body["password"]
            )


            # Blank means preserve current password.

            if password:

                config["wifi"]["password"] = (
                    password
                )


        if "ntp_server" in body:

            ntp_server = str(
                body["ntp_server"]
            ).strip()

            if ntp_server:
                config["time"]["ntp_server"] = ntp_server


        if "timezone" in body:

            timezone = str(
                body["timezone"]
            ).strip()

            if timezone:
                config["time"]["timezone"] = timezone


        if "sync_interval_hours" in body:

            try:
                interval = int(
                    body["sync_interval_hours"]
                )
            except:
                interval = DEFAULT_NTP_SYNC_INTERVAL_HOURS

            if interval < 1:
                interval = 1

            if interval > 168:
                interval = 168

            config["time"]["sync_interval_hours"] = interval


        if "weather_enabled" in body:
            config["weather"]["enabled"] = bool(
                body["weather_enabled"]
            )

        if "weather_zip_code" in body:
            config["weather"]["zip_code"] = str(
                body["weather_zip_code"]
            ).strip()

        if "weather_country_code" in body:

            country_code = str(
                body["weather_country_code"]
            ).strip().upper()

            if not country_code:
                country_code = "US"

            config["weather"]["country_code"] = (
                country_code
            )

        if "weather_latitude" in body:

            try:
                config["weather"]["latitude"] = float(
                    body["weather_latitude"]
                )
            except:
                pass

        if "weather_longitude" in body:

            try:
                config["weather"]["longitude"] = float(
                    body["weather_longitude"]
                )
            except:
                pass

        if "weather_refresh_minutes" in body:

            try:
                minutes = int(
                    body["weather_refresh_minutes"]
                )
            except:
                minutes = DEFAULT_WEATHER_REFRESH_MINUTES

            if minutes < 5:
                minutes = 5

            if minutes > 1440:
                minutes = 1440

            config["weather"]["refresh_minutes"] = minutes

        if "block_rain_threshold_in" in body:

            try:
                value = float(
                    body["block_rain_threshold_in"]
                )
                if value < 0:
                    value = 0
                config["event_blocks"]["rain_threshold_in"] = value
            except:
                pass

        if "block_rain_lookback_days" in body:

            try:
                value = int(
                    body["block_rain_lookback_days"]
                )
                if value < 1:
                    value = 1
                if value > 4:
                    value = 4
                config["event_blocks"]["rain_lookback_days"] = value
            except:
                pass

        if "block_wind_max_mph" in body:

            try:
                value = float(
                    body["block_wind_max_mph"]
                )
                if value < 0:
                    value = 0
                config["event_blocks"]["wind_max_mph"] = value
            except:
                pass

        if "relays" in body:

            names = body["relays"]


            for index in range(
                min(
                    6,
                    len(names)
                )
            ):

                name = str(
                    names[index]
                ).strip()


                if not name:

                    name = (
                        "Relay {}"
                        .format(index + 1)
                    )


                config["relays"][index]["name"] = (
                    name
                )


        if not save_config():

            return {
                "error":
                    "Unable to save configuration"
            }, 500


        return {
            "saved": True
        }


    # --------------------------------------------------------
    # INDIVIDUAL RELAY
    # --------------------------------------------------------

    @app.get("/api/relay/<int:number>")
    async def api_relay_get(
        request,
        number
    ):

        if not valid_relay(number):

            return {
                "error":
                    "Invalid relay"
            }, 400


        return {

            "relay":
                number,

            "name":
                config["relays"][
                    number - 1
                ].get(
                    "name",
                    "Relay {}".format(number)
                ),

            "state":
                relay_get(number)
        }


    @app.put("/api/relay/<int:number>")
    async def api_relay_set(
        request,
        number
    ):

        if not valid_relay(number):

            return {
                "error":
                    "Invalid relay"
            }, 400


        body = request.json


        if (
            body is None
            or
            "state" not in body
        ):

            return {
                "error":
                    "JSON state field required"
            }, 400


        new_state = bool(
            body["state"]
        )

        relay_set(
            number,
            new_state
        )

        log_manual_relay_action(
            "relay_on"
            if new_state
            else "relay_off",
            relay_number=number,
            relay_state=new_state
        )

        return get_status()


    @app.post("/api/relay/<int:number>/on")
    async def api_relay_on(
        request,
        number
    ):

        if not valid_relay(number):

            return {
                "error":
                    "Invalid relay"
            }, 400


        relay_on(number)

        log_manual_relay_action(
            "relay_on",
            relay_number=number,
            relay_state=True
        )

        return get_status()


    @app.post("/api/relay/<int:number>/off")
    async def api_relay_off(
        request,
        number
    ):

        if not valid_relay(number):

            return {
                "error":
                    "Invalid relay"
            }, 400


        relay_off(number)

        log_manual_relay_action(
            "relay_off",
            relay_number=number,
            relay_state=False
        )

        return get_status()


    @app.post("/api/relay/<int:number>/toggle")
    async def api_relay_toggle(
        request,
        number
    ):

        if not valid_relay(number):

            return {
                "error":
                    "Invalid relay"
            }, 400


        relay_toggle(number)

        new_state = relay_get(
            number
        )

        log_manual_relay_action(
            "relay_on"
            if new_state
            else "relay_off",
            relay_number=number,
            relay_state=new_state
        )

        return get_status()


    # --------------------------------------------------------
    # ALL RELAYS
    # --------------------------------------------------------

    @app.post("/api/relays/on")
    async def api_all_on(request):

        all_relays_on()

        log_manual_relay_action(
            "all_on",
            relay_state=True,
            all_relays=True
        )

        return get_status()


    @app.post("/api/relays/off")
    async def api_all_off(request):

        all_relays_off()

        log_manual_relay_action(
            "all_off",
            relay_state=False,
            all_relays=True
        )

        return get_status()


    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    @app.get("/api/time")
    async def api_time(request):

        return get_time_status()


    @app.post("/api/time/sync")
    async def api_time_sync(request):

        success = sync_time()

        return {
            "success": success,
            "time": get_time_status()
        }, (200 if success else 503)


    # --------------------------------------------------------
    # WEATHER
    # --------------------------------------------------------

    @app.get("/api/weather")
    async def api_weather(request):

        return get_weather_status()


    @app.post("/api/weather/refresh")
    async def api_weather_refresh(request):

        success = refresh_weather()

        return {
            "success": success,
            "weather": get_weather_status()
        }, (200 if success else 503)


    # --------------------------------------------------------
    # EVENTS
    # --------------------------------------------------------

    @app.get("/api/events")
    async def api_events(request):

        return get_events_status()


    @app.post("/api/events")
    async def api_add_event(request):

        if events_service is None:
            return {"error": "Event scheduler unavailable"}, 503

        body = request.json

        if not body:
            return {"error": "JSON body required"}, 400

        try:
            event = events_service.add(body)
            return {"saved": True, "event": event}, 201
        except Exception as e:
            return {"error": str(e)}, 400


    @app.put("/api/events/<int:event_id>")
    async def api_update_event(request, event_id):

        if events_service is None:
            return {"error": "Event scheduler unavailable"}, 503

        body = request.json

        if not body:
            return {"error": "JSON body required"}, 400

        try:
            event = events_service.update(event_id, body)
            return {"saved": True, "event": event}
        except Exception as e:
            return {"error": str(e)}, 400


    @app.delete("/api/events/<int:event_id>")
    async def api_delete_event(request, event_id):

        if events_service is None:
            return {"error": "Event scheduler unavailable"}, 503

        try:
            event = events_service.remove(event_id)
            return {"deleted": True, "event": event}
        except Exception as e:
            return {"error": str(e)}, 404


    @app.get("/api/events/upcoming")
    async def api_events_upcoming(request):

        try:

            return {
                "available":
                    events_service is not None,

                "time_synchronized":
                    bool(
                        time_synchronized
                    ),

                "upcoming":
                    get_upcoming_events(3),

                "error":
                    None
            }

        except Exception as e:

            print(
                "Upcoming events API error:",
                repr(e)
            )

            return {
                "available":
                    events_service is not None,

                "time_synchronized":
                    bool(
                        time_synchronized
                    ),

                "upcoming":
                    [],

                "error":
                    repr(e)
            }, 500


    @app.get("/api/events/log")
    async def api_event_log(request):

        return {
            "log": get_event_log(50)
        }


    @app.delete("/api/events/log")
    async def api_clear_event_log(request):

        if events_service is None:
            return {"error": "Event scheduler unavailable"}, 503

        events_service.clear_log()

        return {
            "cleared": True
        }


    # --------------------------------------------------------
    # REBOOT
    # --------------------------------------------------------

    @app.post("/api/reboot")
    async def api_reboot(request):

        schedule_reboot()

        return {
            "restarting": True
        }


# ============================================================
# PERIODIC TIME SYNCHRONIZATION / ASYNC SERVER
# ============================================================

async def periodic_time_sync_task():

    import asyncio

    while True:

        await asyncio.sleep(
            ntp_sync_interval_seconds()
        )

        if wifi_is_connected():
            sync_time()

        gc.collect()


async def periodic_weather_task():

    import asyncio

    while True:

        await asyncio.sleep(
            weather_refresh_interval_seconds()
        )

        if wifi_is_connected():
            refresh_weather()

        gc.collect()


async def periodic_event_task():

    import asyncio

    while True:

        if events_service is not None:
            events_service.process()

        await asyncio.sleep(10)



async def diagnostic_tcp_server():
    """Minimal raw TCP/HTTP diagnostic server on port 8081.

    This bypasses Microdot completely. If this listener is reachable over USB
    while Microdot on port 80 is not, the remaining problem is in the Microdot
    server path. If this listener is also unreachable, the remaining problem is
    in TCP/socket handling below Microdot.
    """

    import asyncio
    import socket

    server = None

    try:
        server = socket.socket()

        try:
            server.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1
            )
        except Exception:
            pass

        server.bind(
            ("0.0.0.0", 8081)
        )

        server.listen(2)
        server.setblocking(False)

        # Green now means that at least one real TCP listening socket has
        # successfully bound.  This is more useful than turning it on before
        # the HTTP/TCP server phase begins.
        red_led(False)
        green_led(True)

        print(
            "Raw TCP diagnostic listening on 0.0.0.0:8081"
        )

    except Exception as e:

        green_led(False)
        red_led(True)

        print(
            "ERROR: Raw TCP diagnostic listener failed:",
            repr(e)
        )

        try:
            if server is not None:
                server.close()
        except Exception:
            pass

        return


    while True:

        client = None

        try:
            client, address = server.accept()

        except OSError:
            await asyncio.sleep_ms(50)
            continue

        except Exception as e:

            print(
                "Raw TCP accept error:",
                repr(e)
            )

            await asyncio.sleep_ms(100)
            continue


        try:

            try:
                client.settimeout(1)
            except Exception:
                pass

            try:
                client.recv(512)
            except Exception:
                pass

            stats = {}

            try:
                if usb_ncm is not None and hasattr(usb_ncm, "stats"):
                    stats = usb_ncm.stats()
            except Exception as e:
                stats = {
                    "error":
                        repr(e)
                }

            body = (
                "TRelay-S3-Controller raw TCP diagnostic OK\n"
                "USB IP: " +
                str(usb_ip()) +
                "\n"
                "Wi-Fi IP: " +
                str(wifi_ip()) +
                "\n"
                "USB stats: " +
                repr(stats) +
                "\n"
            )

            body_bytes = body.encode()

            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n"
                "Content-Length: " +
                str(len(body_bytes)) +
                "\r\n"
                "\r\n"
            ).encode() + body_bytes

            client.sendall(
                response
            )

            print(
                "Raw TCP diagnostic request from:",
                address
            )

        except Exception as e:

            print(
                "Raw TCP diagnostic client error:",
                repr(e)
            )

        finally:

            try:
                client.close()
            except Exception:
                pass



async def run_async_services():

    import asyncio

    # Start a low-level diagnostic listener first. Yield once so the socket is
    # bound before Microdot attempts to start.
    asyncio.create_task(
        diagnostic_tcp_server()
    )

    await asyncio.sleep_ms(0)

    asyncio.create_task(
        periodic_time_sync_task()
    )

    if weather_service is not None:

        asyncio.create_task(
            periodic_weather_task()
        )

    if events_service is not None:

        asyncio.create_task(
            periodic_event_task()
        )

    print(
        "Starting Microdot on 0.0.0.0:{}...".format(
            WEB_PORT
        )
    )

    # Do not emit periodic runtime diagnostics over USB CDC. CDC and NCM share
    # the composite USB device; keep steady-state USB traffic dedicated to NCM.

    try:

        await app.start_server(
            host="0.0.0.0",
            port=WEB_PORT,
            debug=True
        )

    except Exception as e:

        print(
            "ERROR: Microdot server failed:",
            repr(e)
        )

        try:
            import sys
            sys.print_exception(e)
        except Exception:
            pass

        raise


def run_web_server():

    import asyncio

    print(
        "Entering asyncio event loop."
    )

    try:

        asyncio.run(
            run_async_services()
        )

    except Exception as e:

        print(
            "ERROR: Web event loop exited:",
            repr(e)
        )

        try:
            import sys
            sys.print_exception(e)
        except Exception:
            pass

        raise


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("============================")
    print("TRelay-S3-Controller")
    print("============================")


    gc.collect()

    print(
        "Initial free memory:",
        gc.mem_free()
    )


    # --------------------------------------------------------
    # Hardware
    # --------------------------------------------------------

    initialize_relays()

    test_relays()
    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    load_config()


    print()
    print(
        "Device:",
        config.get(
            "device_name",
            "TRelay-S3-Controller"
        )
    )


    gc.collect()


    # --------------------------------------------------------
    # Network interfaces.
    #
    # USB is initialized first and may be used for HTTP even when the
    # configured Wi-Fi network is unavailable.  Wi-Fi is still used for
    # upstream Internet services such as NTP and weather.
    # --------------------------------------------------------

    usb_available = initialize_usb_network()
    wifi_connected = connect_wifi()

    if not usb_available and not wifi_connected:

        red_led(True)
        green_led(False)

        print()
        print("============================")
        print("STARTUP STOPPED")
        print("============================")

        print()
        print(
            "Neither USB NCM nor Wi-Fi networking is available."
        )

        print(
            "Microdot was NOT started."
        )

        return


    # --------------------------------------------------------
    # Internet-dependent services.
    #
    # USB NCM is intentionally not assumed to provide a default gateway.
    # NTP and weather remain tied to successful Wi-Fi connectivity.
    # --------------------------------------------------------

    if wifi_connected:

        # Synchronize the RTC from NTP. A failure does not prevent
        # the relay controller or web server from starting.
        resolve_weather_location_from_zip()

        sync_time()

        # Initialize and fetch weather. Failure does not stop
        # relay control or the web server.
        if initialize_weather():
            refresh_weather()

    else:

        print()
        print(
            "Wi-Fi is unavailable. HTTP will remain available over USB."
        )

        print(
            "NTP and weather startup refresh were skipped."
        )


    # Load persistent events even if the clock is not synchronized.
    # EventService already receives time_is_synchronized and can avoid
    # treating an unsynchronized RTC as valid scheduler time.
    initialize_events()

    # Keep the readiness LED off until a TCP listener has actually bound.
    # diagnostic_tcp_server() turns green on after port 8081 is listening.
    red_led(False)
    green_led(False)


    # --------------------------------------------------------
    # Web server
    #
    # Start the diagnostic TCP listener and Microdot. The diagnostic listener
    # on port 8081 bypasses Microdot so TCP/socket operation can be tested
    # independently from the application web framework.
    # --------------------------------------------------------

    initialize_web_server()

    gc.collect()

    # This call normally does not return. The server binds to 0.0.0.0,
    # therefore the same listener accepts HTTP over both Wi-Fi and USB NCM.
    run_web_server()


# ============================================================
# START
# ============================================================

main()

