# ============================================================
# events.py
# Persistent scheduler for the Sprinklers1 MicroPython app.
# ============================================================

import gc
import json
import socket
import ssl

EVENTS_FILE = "/events.json"
LEGACY_EVENT_LOG_FILE = "/event_log.json"

EVENTS_FILE_VERSION = 2
CURRENT_EVENT_VERSION = 3
CURRENT_LOG_VERSION = 1

MAX_LOG_ENTRIES = 100

DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday"
]

VALID_ACTIONS = (
    "relay_on",
    "relay_off",
    "all_relays_on",
    "all_relays_off",
    "get_url",
)


def _url_encode(value):
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    out = ""
    for ch in str(value):
        if ch in safe:
            out += ch
        elif ch == " ":
            out += "%20"
        else:
            for b in ch.encode("utf-8"):
                out += "%%%02X" % b
    return out


def _parse_url(url):
    if url.startswith("https://"):
        secure = True
        rest = url[8:]
        default_port = 443
    elif url.startswith("http://"):
        secure = False
        rest = url[7:]
        default_port = 80
    else:
        raise ValueError("URL must start with http:// or https://")

    slash = rest.find("/")
    if slash < 0:
        host_part = rest
        path = "/"
    else:
        host_part = rest[:slash]
        path = rest[slash:]

    if ":" in host_part:
        host, port_text = host_part.rsplit(":", 1)
        port = int(port_text)
    else:
        host = host_part
        port = default_port

    return secure, host, port, path


def _decode_chunked(body):
    output = bytearray()
    pos = 0

    while True:
        end = body.find(b"\r\n", pos)
        if end < 0:
            break

        size_text = body[pos:end].split(b";", 1)[0]
        size = int(size_text, 16)
        pos = end + 2

        if size == 0:
            break

        output.extend(body[pos:pos + size])
        pos += size + 2

    return bytes(output)


def http_get_json(url):
    """GET a JSON URL using requests/urequests or a socket fallback."""

    response = None

    try:
        try:
            import requests
        except ImportError:
            import urequests as requests

        response = requests.get(url)

        if hasattr(response, "status_code") and response.status_code != 200:
            raise OSError("HTTP status %s" % response.status_code)

        return response.json()

    except ImportError:
        pass

    finally:
        if response is not None:
            try:
                response.close()
            except:
                pass

    secure, host, port, path = _parse_url(url)
    address = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()

    try:
        sock.settimeout(10)
        sock.connect(address)

        if secure:
            try:
                sock = ssl.wrap_socket(sock, server_hostname=host)
            except TypeError:
                sock = ssl.wrap_socket(sock)

        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s\r\n"
            "User-Agent: Sprinklers1/1.0\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n\r\n"
        ) % (path, host)

        sock.write(request.encode())
        raw = bytearray()

        while True:
            block = sock.read(1024)
            if not block:
                break
            raw.extend(block)

    finally:
        try:
            sock.close()
        except:
            pass

    header_end = raw.find(b"\r\n\r\n")
    if header_end < 0:
        raise OSError("Invalid HTTP response")

    headers = bytes(raw[:header_end])
    body = bytes(raw[header_end + 4:])
    status_line = headers.split(b"\r\n", 1)[0]

    if b" 200 " not in status_line:
        raise OSError("HTTP error: %s" % status_line)

    if b"transfer-encoding: chunked" in headers.lower():
        body = _decode_chunked(body)

    return json.loads(body.decode())


class EventService:

    def __init__(
        self,
        relay_on,
        relay_off,
        all_relays_on,
        all_relays_off,
        relay_get,
        relay_name,
        relay_number_from_name,
        local_time_tuple,
        local_time_string,
        current_temperature,
        current_wind,
        recent_rain,
        block_settings,
        time_is_synchronized,
    ):
        self._relay_on = relay_on
        self._relay_off = relay_off
        self._all_relays_on = all_relays_on
        self._all_relays_off = all_relays_off
        self._relay_get = relay_get
        self._relay_name = relay_name
        self._relay_number_from_name = relay_number_from_name
        self._local_time_tuple = local_time_tuple
        self._local_time_string = local_time_string
        self._current_temperature = current_temperature
        self._current_wind = current_wind
        self._recent_rain = recent_rain
        self._block_settings = block_settings
        self._time_is_synchronized = time_is_synchronized

        self.events = []
        self.next_id = 1
        self.log = []
        self._processed = {}

        self.load()

    # --------------------------------------------------------
    # Persistence and migrations
    # --------------------------------------------------------

    def _default_store(self):

        return {
            "file_version":
                EVENTS_FILE_VERSION,

            "next_event_id":
                1,

            "events":
                [],

            "log":
                []
        }


    def _read_json_file(
        self,
        filename,
        default=None
    ):

        try:

            with open(
                filename,
                "r"
            ) as f:

                return json.load(f)

        except:

            return default


    def _atomic_write_store(self):

        import os

        temp = EVENTS_FILE + ".tmp"

        payload = {
            "file_version":
                EVENTS_FILE_VERSION,

            "next_event_id":
                self.next_id,

            "events":
                self.events,

            "log":
                self.log[
                    -MAX_LOG_ENTRIES:
                ]
        }

        with open(
            temp,
            "w"
        ) as f:

            json.dump(
                payload,
                f
            )

        try:
            os.remove(
                EVENTS_FILE
            )
        except:
            pass

        os.rename(
            temp,
            EVENTS_FILE
        )


    def _migrate_file_v1_to_v2(
        self,
        data
    ):
        """
        Old layout:

            {
                "next_id": ...,
                "events": [...]
            }

        plus a separate event_log.json file.

        New layout stores events and log together.
        """

        log = data.get(
            "log",
            None
        )

        if not isinstance(
            log,
            list
        ):

            legacy_log = self._read_json_file(
                LEGACY_EVENT_LOG_FILE,
                []
            )

            log = (
                legacy_log
                if isinstance(
                    legacy_log,
                    list
                )
                else []
            )

        return {
            "file_version":
                2,

            "next_event_id":
                int(
                    data.get(
                        "next_event_id",
                        data.get(
                            "next_id",
                            1
                        )
                    )
                ),

            "events":
                data.get(
                    "events",
                    []
                ),

            "log":
                log
        }


    def _migrate_store_to_current(
        self,
        data
    ):

        if not isinstance(
            data,
            dict
        ):

            data = (
                self._default_store()
            )

        # A legacy events.json has no file_version.
        version = int(
            data.get(
                "file_version",
                1
            )
        )

        while (
            version <
            EVENTS_FILE_VERSION
        ):

            if version == 1:

                data = (
                    self._migrate_file_v1_to_v2(
                        data
                    )
                )

                version = 2

            else:

                raise ValueError(
                    "No events-file migration "
                    "from version {}".format(
                        version
                    )
                )

        if (
            version >
            EVENTS_FILE_VERSION
        ):

            raise ValueError(
                "events.json file version {} "
                "is newer than supported {}".format(
                    version,
                    EVENTS_FILE_VERSION
                )
            )

        return data


    def _migrate_event_v1_to_v2(
        self,
        event
    ):
        """
        Version 2 introduced the global weather-block opt-ins.
        Older records default to not using either block.
        """

        event.setdefault(
            "skip_if_recent_rain",
            False
        )

        event.setdefault(
            "skip_if_high_wind",
            False
        )

        event[
            "record_version"
        ] = 2

        return event


    def _migrate_event_v2_to_v3(
        self,
        event
    ):
        """
        Version 3 introduced skip_next.

        Existing events default to False so an upgrade never
        unexpectedly skips a scheduled occurrence.
        """

        event.setdefault(
            "skip_next",
            False
        )

        event[
            "record_version"
        ] = 3

        return event


    def _migrate_event_to_current(
        self,
        event
    ):

        if not isinstance(
            event,
            dict
        ):

            raise ValueError(
                "Event record is not an object"
            )

        # Records created before versioning are version 1.
        version = int(
            event.get(
                "record_version",
                1
            )
        )

        migrated = dict(event)

        while (
            version <
            CURRENT_EVENT_VERSION
        ):

            if version == 1:

                migrated = (
                    self._migrate_event_v1_to_v2(
                        migrated
                    )
                )

                version = 2

            elif version == 2:

                migrated = (
                    self._migrate_event_v2_to_v3(
                        migrated
                    )
                )

                version = 3

            else:

                raise ValueError(
                    "No event migration "
                    "from version {}".format(
                        version
                    )
                )

        if (
            version >
            CURRENT_EVENT_VERSION
        ):

            raise ValueError(
                "Event record version {} "
                "is newer than supported {}".format(
                    version,
                    CURRENT_EVENT_VERSION
                )
            )

        migrated[
            "record_version"
        ] = (
            CURRENT_EVENT_VERSION
        )

        return migrated


    def _migrate_log_to_current(
        self,
        entry
    ):

        if not isinstance(
            entry,
            dict
        ):

            return None

        migrated = dict(entry)

        version = int(
            migrated.get(
                "record_version",
                1
            )
        )

        if (
            version >
            CURRENT_LOG_VERSION
        ):

            # Keep unknown newer log records rather than
            # destroying historical data.
            return migrated

        migrated[
            "record_version"
        ] = (
            CURRENT_LOG_VERSION
        )

        return migrated


    def load(self):

        import os

        raw = self._read_json_file(
            EVENTS_FILE,
            None
        )

        if raw is None:

            data = (
                self._default_store()
            )

        else:

            data = (
                self._migrate_store_to_current(
                    raw
                )
            )

        self.next_id = int(
            data.get(
                "next_event_id",
                data.get(
                    "next_id",
                    1
                )
            )
        )

        self.events = []

        changed = (
            raw is None
            or
            int(
                data.get(
                    "file_version",
                    1
                )
            )
            !=
            EVENTS_FILE_VERSION
        )

        for source_event in data.get(
            "events",
            []
        ):

            try:

                migrated = (
                    self._migrate_event_to_current(
                        source_event
                    )
                )

                # Re-run current validation and normalization.
                clean = self._clean_event(
                    migrated,
                    migrated.get(
                        "id"
                    )
                )

                self.events.append(
                    clean
                )

                if (
                    source_event != clean
                ):
                    changed = True

            except Exception as e:

                print(
                    "Skipping invalid event "
                    "during migration:",
                    repr(e)
                )

        self.log = []

        for entry in data.get(
            "log",
            []
        ):

            migrated = (
                self._migrate_log_to_current(
                    entry
                )
            )

            if migrated is not None:

                self.log.append(
                    migrated
                )

        if (
            len(self.log) >
            MAX_LOG_ENTRIES
        ):

            self.log = self.log[
                -MAX_LOG_ENTRIES:
            ]

            changed = True

        # Ensure next_id remains above all existing IDs.
        maximum_id = 0

        for event in self.events:

            try:

                event_id = int(
                    event.get(
                        "id",
                        0
                    ) or 0
                )

                if event_id > maximum_id:
                    maximum_id = event_id

            except:
                pass

        if (
            self.next_id <=
            maximum_id
        ):

            self.next_id = (
                maximum_id + 1
            )

            changed = True

        # Write the combined/current representation immediately
        # after migration. Only after a successful write do we
        # delete the legacy event_log.json file.
        self._atomic_write_store()

        try:

            if (
                LEGACY_EVENT_LOG_FILE.lstrip("/")
                in os.listdir("/")
            ):

                os.remove(
                    LEGACY_EVENT_LOG_FILE
                )

                print(
                    "Migrated legacy event_log.json "
                    "into events.json."
                )

        except Exception as e:

            print(
                "Legacy event log cleanup warning:",
                repr(e)
            )


    def save(self):

        self._atomic_write_store()


    def save_log(self):

        # Logs and events intentionally share one durable file.
        self._atomic_write_store()


    # --------------------------------------------------------
    # Event management
    # --------------------------------------------------------

    def _clean_event(self, data, event_id=None):
        action = str(data.get("action", "")).strip()
        if action not in VALID_ACTIONS:
            raise ValueError("Invalid action")

        time_value = str(data.get("time", "")).strip()
        pieces = time_value.split(":")
        if len(pieces) != 2:
            raise ValueError("Time must be HH:MM")

        hour = int(pieces[0])
        minute = int(pieces[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Invalid event time")

        days = []
        for day in data.get("days", []):
            day = int(day)
            if 0 <= day <= 6 and day not in days:
                days.append(day)
        days.sort()

        if not days:
            raise ValueError("At least one day is required")

        relay_number = data.get("relay_number", None)
        if relay_number in ("", None):
            relay_number = None
        else:
            relay_number = int(relay_number)
            if relay_number < 1 or relay_number > 6:
                raise ValueError("Relay must be 1 through 6")

        if action in ("relay_on", "relay_off") and relay_number is None:
            raise ValueError("Relay action requires relay_number")

        def optional_float(name):
            value = data.get(name, None)
            if value in (None, ""):
                return None
            return float(value)

        minimum = optional_float("min_temp_f")
        maximum = optional_float("max_temp_f")

        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum temperature exceeds maximum")

        url_mode = str(data.get("url_relay_mode", "none")).lower()
        if url_mode not in ("none", "number", "name"):
            url_mode = "none"

        result = {
            "record_version":
                CURRENT_EVENT_VERSION,

            "id": event_id,
            "name": str(data.get("name", "Event")).strip() or "Event",
            "enabled": bool(data.get("enabled", True)),
            "days": days,
            "time": "%02d:%02d" % (hour, minute),
            "action": action,
            "relay_number": relay_number,
            "min_temp_f": minimum,
            "max_temp_f": maximum,
            "skip_if_recent_rain": bool(
                data.get(
                    "skip_if_recent_rain",
                    False
                )
            ),
            "skip_if_high_wind": bool(
                data.get(
                    "skip_if_high_wind",
                    False
                )
            ),
            "skip_next": bool(
                data.get(
                    "skip_next",
                    False
                )
            ),
            "url": str(data.get("url", "")).strip(),
            "url_relay_mode": url_mode,
            "url_relay_number": data.get("url_relay_number", None),
            "url_include_state": bool(data.get("url_include_state", False)),
        }

        if result["url_relay_number"] in ("", None):
            result["url_relay_number"] = None
        else:
            result["url_relay_number"] = int(result["url_relay_number"])
            if result["url_relay_number"] < 1 or result["url_relay_number"] > 6:
                raise ValueError("GET URL relay must be 1 through 6")

        if action == "get_url" and not result["url"]:
            raise ValueError("GET URL action requires a URL")

        return result

    def add(self, data):
        event = self._clean_event(
            data,
            self.next_id
        )

        # skip_next is an operational control for an existing
        # event, not an event-creation option.
        event["skip_next"] = False

        self.next_id += 1
        self.events.append(event)
        self.save()
        return event

    def update(self, event_id, data):
        event_id = int(event_id)
        for index, current in enumerate(self.events):
            if int(current.get("id", -1)) == event_id:
                event = self._clean_event(data, event_id)
                self.events[index] = event
                self.save()
                return event
        raise ValueError("Event not found")

    def remove(self, event_id):
        event_id = int(event_id)
        for index, event in enumerate(self.events):
            if int(event.get("id", -1)) == event_id:
                removed = self.events.pop(index)
                self._processed.pop(event_id, None)
                self.save()
                return removed
        raise ValueError("Event not found")

    def list_events(self):
        return self.events

    # --------------------------------------------------------
    # Upcoming schedule
    # --------------------------------------------------------

    def upcoming(self, limit=3):
        """
        Return the next scheduled event occurrences.

        Recurring events are expanded into future occurrences.
        For example, one event scheduled every Monday can occupy
        all three returned slots: next Monday, the following
        Monday, and the Monday after that.
        """

        if not self._time_is_synchronized():
            return []

        try:
            limit = int(limit)
        except:
            limit = 3

        if limit < 1:
            limit = 1

        if limit > 10:
            limit = 10

        now = self._local_time_tuple()

        if now is None or len(now) < 7:
            return []

        current_weekday = int(now[6])
        current_minutes = (
            int(now[3]) * 60 +
            int(now[4])
        )

        minute_key = "%04d%02d%02d%02d%02d" % (
            int(now[0]),
            int(now[1]),
            int(now[2]),
            int(now[3]),
            int(now[4])
        )

        occurrences = []

        # Eight weeks is more than enough to produce the next
        # three occurrences for any normal weekly schedule.
        WEEKS_TO_SEARCH = 8

        for event in self.events:

            try:

                if not isinstance(event, dict):
                    continue

                if not event.get(
                    "enabled",
                    True
                ):
                    continue

                time_value = str(
                    event.get(
                        "time",
                        ""
                    )
                )

                pieces = time_value.split(":")

                if len(pieces) != 2:
                    continue

                hour = int(pieces[0])
                minute = int(pieces[1])

                if (
                    hour < 0
                    or hour > 23
                    or minute < 0
                    or minute > 59
                ):
                    continue

                event_minutes = (
                    hour * 60 +
                    minute
                )

                days = event.get(
                    "days",
                    []
                )

                if not isinstance(
                    days,
                    (list, tuple)
                ):
                    continue

                event_id = int(
                    event.get(
                        "id",
                        0
                    ) or 0
                )

                for raw_day in days:

                    try:
                        event_day = int(
                            raw_day
                        )
                    except:
                        continue

                    if (
                        event_day < 0
                        or event_day > 6
                    ):
                        continue

                    base_day_delta = (
                        event_day -
                        current_weekday
                    ) % 7

                    base_delta = (
                        base_day_delta * 1440 +
                        event_minutes -
                        current_minutes
                    )

                    # If today's scheduled time has already
                    # passed, move this first occurrence to
                    # next week.
                    if base_delta < 0:
                        base_delta += (
                            7 * 1440
                        )

                    # If this exact event already fired/skipped
                    # during the current minute, do not display
                    # the current minute as "upcoming".
                    if (
                        base_delta == 0
                        and
                        self._processed.get(
                            event_id
                        ) == minute_key
                    ):
                        base_delta += (
                            7 * 1440
                        )

                    for week_offset in range(
                        WEEKS_TO_SEARCH
                    ):

                        delta = (
                            base_delta +
                            week_offset *
                            7 *
                            1440
                        )

                        action = str(
                            event.get(
                                "action",
                                ""
                            )
                        )

                        item = {
                            "id":
                                event.get(
                                    "id"
                                ),

                            "name":
                                str(
                                    event.get(
                                        "name",
                                        "Event"
                                    )
                                ),

                            "action":
                                action,

                            "day":
                                event_day,

                            "day_name":
                                DAY_NAMES[
                                    event_day
                                ],

                            "time":
                                "%02d:%02d" % (
                                    hour,
                                    minute
                                ),

                            "minutes_until":
                                delta,

                            "weeks_ahead":
                                week_offset
                        }

                        # URL events intentionally omit all
                        # temperature information.
                        if action != "get_url":

                            item[
                                "min_temp_f"
                            ] = event.get(
                                "min_temp_f"
                            )

                            item[
                                "max_temp_f"
                            ] = event.get(
                                "max_temp_f"
                            )

                        occurrences.append(
                            item
                        )

            except Exception as e:

                print(
                    "Skipping malformed event "
                    "while building upcoming list:",
                    repr(e)
                )

        occurrences.sort(
            key=lambda item:
                item.get(
                    "minutes_until",
                    99999999
                )
        )

        # skip_next applies to exactly one future occurrence:
        # the first chronological occurrence for that event.
        pending_skip = {}

        for event in self.events:

            try:
                event_id = int(
                    event.get(
                        "id",
                        0
                    ) or 0
                )
            except:
                continue

            if event.get(
                "skip_next",
                False
            ):
                pending_skip[
                    event_id
                ] = True

        skip_marked = {}

        for item in occurrences:

            try:
                event_id = int(
                    item.get(
                        "id",
                        0
                    ) or 0
                )
            except:
                event_id = 0

            if (
                pending_skip.get(
                    event_id,
                    False
                )
                and
                not skip_marked.get(
                    event_id,
                    False
                )
            ):

                item[
                    "skip_next"
                ] = True

                skip_marked[
                    event_id
                ] = True

            else:

                item[
                    "skip_next"
                ] = False

        return occurrences[:limit]


    # --------------------------------------------------------
    # Log
    # --------------------------------------------------------

    def _append_log(self, event, status, temperature, reason="", detail=""):
        entry = {
            "record_version":
                CURRENT_LOG_VERSION,

            "time": self._local_time_string(),
            "event_id": event.get("id"),
            "event_name": event.get("name", "Event"),
            "action": event.get("action", ""),
            "status": status,
            "temperature_f": temperature,
            "reason": reason,
            "detail": detail,
        }
        self.log.append(entry)
        if len(self.log) > MAX_LOG_ENTRIES:
            self.log = self.log[-MAX_LOG_ENTRIES:]
        self.save_log()

    def recent_log(self, limit=50):
        limit = int(limit)
        if limit < 1:
            limit = 1
        if limit > MAX_LOG_ENTRIES:
            limit = MAX_LOG_ENTRIES
        return list(reversed(self.log[-limit:]))


    def log_manual(
        self,
        action,
        event_name,
        detail="",
        relay_number=None,
        relay_state=None
    ):
        """
        Add a manually initiated relay action to the event log.

        This is intentionally separate from scheduled-event
        execution so scheduled events are not double-logged.
        """

        entry = {
            "record_version":
                CURRENT_LOG_VERSION,

            "time":
                self._local_time_string(),

            "event_id":
                None,

            "event_name":
                event_name,

            "action":
                action,

            "status":
                "manual",

            "temperature_f":
                None,

            "reason":
                "manually initiated",

            "detail":
                detail,

            "relay_number":
                relay_number,

            "relay_state":
                relay_state,
        }

        self.log.append(entry)

        if len(self.log) > MAX_LOG_ENTRIES:
            self.log = self.log[
                -MAX_LOG_ENTRIES:
            ]

        self.save_log()

    def clear_log(self):
        self.log = []
        self.save_log()

    # --------------------------------------------------------
    # Execution
    # --------------------------------------------------------

    def _temperature_allowed(self, event, temperature):
        minimum = event.get("min_temp_f")
        maximum = event.get("max_temp_f")

        if minimum is None and maximum is None:
            return True, ""

        if temperature is None:
            return False, "temperature unavailable"

        if minimum is not None and temperature < minimum:
            return False, "temperature below minimum"

        if maximum is not None and temperature > maximum:
            return False, "temperature above maximum"

        return True, ""

    def _global_blocks_allowed(self, event):

        settings = self._block_settings()

        if event.get(
            "skip_if_recent_rain",
            False
        ):

            rain = self._recent_rain()

            if rain is None:

                return (
                    False,
                    "recent rain unavailable",
                    None,
                    None
                )

            threshold = float(
                settings.get(
                    "rain_threshold_in",
                    0.25
                )
            )

            if rain >= threshold:

                return (
                    False,
                    "recent rain %.2f in >= %.2f in block" % (
                        rain,
                        threshold
                    ),
                    rain,
                    None
                )

        if event.get(
            "skip_if_high_wind",
            False
        ):

            wind = self._current_wind()

            if wind is None:

                return (
                    False,
                    "wind unavailable",
                    None,
                    None
                )

            maximum = float(
                settings.get(
                    "wind_max_mph",
                    15.0
                )
            )

            if wind >= maximum:

                return (
                    False,
                    "wind %.1f mph >= %.1f mph block" % (
                        wind,
                        maximum
                    ),
                    None,
                    wind
                )

        return (
            True,
            "",
            None,
            None
        )

    def _append_query(self, url, key, value):
        separator = "&" if "?" in url else "?"
        return url + separator + _url_encode(key) + "=" + _url_encode(value)

    def _run_get_url(self, event):
        url = event.get("url", "")
        relay_number = event.get("url_relay_number")
        mode = event.get("url_relay_mode", "none")

        if mode != "none" and relay_number is not None:
            if mode == "number":
                url = self._append_query(url, "relay_number", relay_number)
            elif mode == "name":
                url = self._append_query(
                    url,
                    "relay_name",
                    self._relay_name(relay_number)
                )

            if event.get("url_include_state", False):
                url = self._append_query(
                    url,
                    "relay_state",
                    "on" if self._relay_get(relay_number) else "off"
                )

        response = http_get_json(url)

        target_number = response.get("relay_number", None)
        target_name = response.get("relay_name", None)

        if target_number is not None:
            target_number = int(target_number)
        elif target_name is not None:
            target_number = self._relay_number_from_name(str(target_name))
        else:
            raise ValueError("GET URL response needs relay_number or relay_name")

        if target_number is None or target_number < 1 or target_number > 6:
            raise ValueError("GET URL returned unknown relay")

        if "relay_state" not in response:
            raise ValueError("GET URL response needs relay_state")

        state = response["relay_state"]
        if isinstance(state, str):
            normalized = state.strip().lower()
            if normalized in ("1", "true", "on", "yes"):
                state = True
            elif normalized in ("0", "false", "off", "no"):
                state = False
            else:
                raise ValueError("Invalid relay_state")
        else:
            state = bool(state)

        if state:
            self._relay_on(target_number)
        else:
            self._relay_off(target_number)

        return "Relay %d set %s" % (
            target_number,
            "ON" if state else "OFF"
        )

    def _execute(self, event):
        action = event.get("action")

        if action == "relay_on":
            number = int(event["relay_number"])
            self._relay_on(number)
            return "Relay %d ON" % number

        if action == "relay_off":
            number = int(event["relay_number"])
            self._relay_off(number)
            return "Relay %d OFF" % number

        if action == "all_relays_on":
            self._all_relays_on()
            return "All relays ON"

        if action == "all_relays_off":
            self._all_relays_off()
            return "All relays OFF"

        if action == "get_url":
            return self._run_get_url(event)

        raise ValueError("Unknown action")

    def process(self):
        if not self._time_is_synchronized():
            return

        now = self._local_time_tuple()
        weekday = now[6]
        hhmm = "%02d:%02d" % (now[3], now[4])
        minute_key = "%04d%02d%02d%02d%02d" % (
            now[0], now[1], now[2], now[3], now[4]
        )

        temperature = self._current_temperature()

        for event in self.events:
            if not event.get("enabled", True):
                continue

            if weekday not in event.get("days", []):
                continue

            if event.get("time") != hhmm:
                continue

            event_id = int(event.get("id", 0))
            if self._processed.get(event_id) == minute_key:
                continue

            self._processed[event_id] = minute_key

            if event.get(
                "skip_next",
                False
            ):

                # Consume this one-shot flag immediately so the
                # following recurrence executes normally.
                event[
                    "skip_next"
                ] = False

                self.save()

                self._append_log(
                    event,
                    "skipped",
                    temperature,
                    "skip next requested",
                    ""
                )

                continue

            allowed, reason = self._temperature_allowed(event, temperature)
            if not allowed:
                self._append_log(
                    event,
                    "skipped",
                    temperature,
                    reason,
                    ""
                )
                continue

            allowed, reason, rain, wind = (
                self._global_blocks_allowed(
                    event
                )
            )

            if not allowed:

                detail_parts = []

                if rain is not None:
                    detail_parts.append(
                        "recent rain %.2f in" % rain
                    )

                if wind is not None:
                    detail_parts.append(
                        "wind %.1f mph" % wind
                    )

                self._append_log(
                    event,
                    "skipped",
                    temperature,
                    reason,
                    ", ".join(
                        detail_parts
                    )
                )

                continue

            try:
                detail = self._execute(event)
                self._append_log(
                    event,
                    "fired",
                    temperature,
                    "",
                    detail
                )
            except Exception as exc:
                # The event matched and fired, but its action failed.
                self._append_log(
                    event,
                    "fired",
                    temperature,
                    "action error",
                    repr(exc)
                )

            gc.collect()
