# ============================================================
# weather.py
#
# Lightweight Open-Meteo weather client for MicroPython.
#
# No API key is required for normal Open-Meteo use.
#
# Tries requests/urequests first. If neither is installed,
# falls back to a small HTTPS client using socket + ssl.
# ============================================================

import gc
import json
import socket
import ssl
import time


OPEN_METEO_HOST = "api.open-meteo.com"
OPEN_METEO_PORT = 443
GEOCODING_HOST = "geocoding-api.open-meteo.com"
GEOCODING_PORT = 443


def _https_get_json(host, port, path):
    """Small HTTPS JSON GET helper used by ZIP geocoding."""

    address = socket.getaddrinfo(
        host,
        port
    )[0][-1]

    sock = socket.socket()

    try:

        sock.settimeout(10)
        sock.connect(address)

        try:
            sock = ssl.wrap_socket(
                sock,
                server_hostname=host
            )
        except TypeError:
            sock = ssl.wrap_socket(sock)

        request = (
            "GET {} HTTP/1.1\r\n"
            "Host: {}\r\n"
            "User-Agent: TRelay-S3-Controller/1.0\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).format(
            path,
            host
        )

        sock.write(
            request.encode()
        )

        response = bytearray()

        while True:

            chunk = sock.read(1024)

            if not chunk:
                break

            response.extend(chunk)

    finally:

        try:
            sock.close()
        except:
            pass

    header_end = response.find(
        b"\r\n\r\n"
    )

    if header_end < 0:
        raise OSError(
            "Invalid HTTP response"
        )

    headers = bytes(
        response[:header_end]
    )

    body = bytes(
        response[header_end + 4:]
    )

    status_line = headers.split(
        b"\r\n",
        1
    )[0]

    if b" 200 " not in status_line:
        raise OSError(
            "HTTP error: {}".format(
                status_line
            )
        )

    # Open-Meteo generally supplies Content-Length for this
    # endpoint, but support chunked encoding as well.
    if b"transfer-encoding: chunked" in headers.lower():

        output = bytearray()
        pos = 0

        while True:

            end = body.find(
                b"\r\n",
                pos
            )

            if end < 0:
                break

            size_text = body[
                pos:end
            ].split(
                b";",
                1
            )[0]

            try:
                size = int(
                    size_text,
                    16
                )
            except:
                break

            pos = end + 2

            if size == 0:
                break

            output.extend(
                body[pos:pos + size]
            )

            pos += size + 2

        body = bytes(output)

    return json.loads(
        body.decode()
    )


def resolve_postal_code(
    postal_code,
    country_code="US"
):
    """
    Resolve a postal/ZIP code to an approximate center point.

    Uses Open-Meteo's geocoding API. The returned coordinates
    represent the matched place/ZIP centroid supplied by the
    geocoder and are suitable for local weather lookup.
    """

    postal_code = str(
        postal_code
    ).strip()

    country_code = str(
        country_code or "US"
    ).strip().upper()

    if not postal_code:
        raise ValueError(
            "Postal code is empty"
        )

    # Keep the request simple so normal US ZIP codes need no
    # URL-encoding beyond digits/hyphen. Spaces are converted.
    query = postal_code.replace(
        " ",
        "%20"
    )

    path = (
        "/v1/search"
        "?name={}"
        "&count=1"
        "&language=en"
        "&format=json"
        "&countryCode={}"
    ).format(
        query,
        country_code
    )

    payload = _https_get_json(
        GEOCODING_HOST,
        GEOCODING_PORT,
        path
    )

    results = payload.get(
        "results",
        []
    )

    if not results:
        raise ValueError(
            "Postal code not found"
        )

    place = results[0]

    return {
        "postal_code":
            postal_code,

        "country_code":
            place.get(
                "country_code",
                country_code
            ),

        "latitude":
            float(
                place["latitude"]
            ),

        "longitude":
            float(
                place["longitude"]
            ),

        "name":
            place.get(
                "name",
                ""
            ),

        "state":
            place.get(
                "admin1",
                ""
            ),

        "timezone":
            place.get(
                "timezone",
                ""
            ),
    }


class WeatherService:

    def __init__(
        self,
        latitude,
        longitude,
        refresh_minutes=30,
    ):
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.refresh_minutes = int(refresh_minutes)

        if self.refresh_minutes < 5:
            self.refresh_minutes = 5

        self.data = {
            "valid": False,
            "stale": True,
            "last_update_epoch": 0,
            "last_error": None,
            "current": {},
            "daily": [],
        }


    def _path(self):

        current = (
            "temperature_2m,"
            "relative_humidity_2m,"
            "precipitation,"
            "weather_code,"
            "wind_speed_10m"
        )

        daily = (
            "precipitation_sum,"
            "precipitation_probability_max,"
            "et0_fao_evapotranspiration,"
            "temperature_2m_max,"
            "temperature_2m_min"
        )

        return (
            "/v1/forecast"
            "?latitude={}"
            "&longitude={}"
            "&current={}"
            "&daily={}"
            "&temperature_unit=fahrenheit"
            "&wind_speed_unit=mph"
            "&precipitation_unit=inch"
            "&forecast_days=3"
            "&past_days=3"
            "&timezone=auto"
        ).format(
            self.latitude,
            self.longitude,
            current,
            daily,
        )


    def _decode_chunked(self, body):

        output = bytearray()
        pos = 0

        while True:

            end = body.find(b"\r\n", pos)

            if end < 0:
                break

            size_text = body[pos:end].split(b";", 1)[0]

            try:
                size = int(size_text, 16)
            except:
                break

            pos = end + 2

            if size == 0:
                break

            output.extend(
                body[pos:pos + size]
            )

            pos += size + 2

        return bytes(output)


    def _socket_get_json(self):

        path = self._path()

        address = socket.getaddrinfo(
            OPEN_METEO_HOST,
            OPEN_METEO_PORT
        )[0][-1]

        sock = socket.socket()

        try:

            sock.settimeout(10)
            sock.connect(address)

            try:
                sock = ssl.wrap_socket(
                    sock,
                    server_hostname=OPEN_METEO_HOST
                )
            except TypeError:
                sock = ssl.wrap_socket(sock)

            request = (
                "GET {} HTTP/1.1\r\n"
                "Host: {}\r\n"
                "User-Agent: TRelay-S3-Controller/1.0\r\n"
                "Accept: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).format(
                path,
                OPEN_METEO_HOST
            )

            sock.write(
                request.encode()
            )

            response = bytearray()

            while True:

                chunk = sock.read(1024)

                if not chunk:
                    break

                response.extend(chunk)

        finally:

            try:
                sock.close()
            except:
                pass

        header_end = response.find(
            b"\r\n\r\n"
        )

        if header_end < 0:
            raise OSError(
                "Invalid HTTP response"
            )

        headers = bytes(
            response[:header_end]
        )

        body = bytes(
            response[header_end + 4:]
        )

        status_line = headers.split(
            b"\r\n",
            1
        )[0]

        if b" 200 " not in status_line:
            raise OSError(
                "Weather HTTP error: {}".format(
                    status_line
                )
            )

        lower_headers = headers.lower()

        if b"transfer-encoding: chunked" in lower_headers:
            body = self._decode_chunked(
                body
            )

        return json.loads(
            body.decode()
        )


    def _get_json(self):

        url = (
            "https://" +
            OPEN_METEO_HOST +
            self._path()
        )

        response = None

        try:

            try:
                import requests
            except ImportError:
                import urequests as requests

            response = requests.get(
                url
            )

            if hasattr(response, "status_code"):
                if response.status_code != 200:
                    raise OSError(
                        "Weather HTTP status {}".format(
                            response.status_code
                        )
                    )

            return response.json()

        except ImportError:

            return self._socket_get_json()

        finally:

            if response is not None:
                try:
                    response.close()
                except:
                    pass


    def _build_daily(self, payload):

        daily = payload.get(
            "daily",
            {}
        )

        dates = daily.get(
            "time",
            []
        )

        result = []

        for index in range(
            len(dates)
        ):

            def value(name):
                values = daily.get(
                    name,
                    []
                )

                if index < len(values):
                    return values[index]

                return None

            result.append({
                "date":
                    dates[index],

                "precipitation_probability":
                    value(
                        "precipitation_probability_max"
                    ),

                "precipitation_in":
                    value(
                        "precipitation_sum"
                    ),

                "et0_in":
                    value(
                        "et0_fao_evapotranspiration"
                    ),

                "temperature_high_f":
                    value(
                        "temperature_2m_max"
                    ),

                "temperature_low_f":
                    value(
                        "temperature_2m_min"
                    ),
            })

        return result


    def refresh(self):

        print()
        print("============================")
        print("REFRESHING WEATHER")
        print("============================")

        print(
            "Location:",
            self.latitude,
            self.longitude
        )

        try:

            gc.collect()

            payload = self._get_json()

            current = payload.get(
                "current",
                {}
            )

            self.data = {
                "valid": True,
                "stale": False,
                "last_update_epoch":
                    time.time(),
                "last_error":
                    None,

                "latitude":
                    payload.get(
                        "latitude",
                        self.latitude
                    ),

                "longitude":
                    payload.get(
                        "longitude",
                        self.longitude
                    ),

                "timezone":
                    payload.get(
                        "timezone",
                        ""
                    ),

                "current": {
                    "time":
                        current.get(
                            "time"
                        ),

                    "temperature_f":
                        current.get(
                            "temperature_2m"
                        ),

                    "humidity_percent":
                        current.get(
                            "relative_humidity_2m"
                        ),

                    "precipitation_in":
                        current.get(
                            "precipitation"
                        ),

                    "weather_code":
                        current.get(
                            "weather_code"
                        ),

                    "wind_mph":
                        current.get(
                            "wind_speed_10m"
                        ),
                },

                "daily":
                    [],

                "history":
                    [],
            }

            all_daily = self._build_daily(
                payload
            )

            current_time = current.get(
                "time",
                ""
            )

            today = (
                current_time[:10]
                if current_time
                else ""
            )

            if today:

                for day in all_daily:

                    day_date = day.get(
                        "date",
                        ""
                    )

                    if day_date < today:
                        self.data["history"].append(
                            day
                        )
                    else:
                        self.data["daily"].append(
                            day
                        )

            else:

                self.data["daily"] = (
                    all_daily[-3:]
                )

            # Limit retained history/forecast to keep RAM usage low.
            self.data["history"] = (
                self.data["history"][-3:]
            )

            self.data["daily"] = (
                self.data["daily"][:3]
            )

            print(
                "Weather update successful."
            )

            return True

        except Exception as e:

            self.data["last_error"] = repr(e)
            self.data["stale"] = True

            print(
                "Weather update failed:",
                repr(e)
            )

            return False

        finally:

            gc.collect()


    def mark_stale_if_needed(self):

        updated = self.data.get(
            "last_update_epoch",
            0
        )

        if not updated:
            self.data["stale"] = True
            return

        age = time.time() - updated

        # Consider data stale after twice the configured
        # refresh interval.
        self.data["stale"] = (
            age >
            self.refresh_minutes * 120
        )


    def status(self):

        self.mark_stale_if_needed()

        return self.data


    def current_wind_mph(self):

        return self.data.get(
            "current",
            {}
        ).get(
            "wind_mph"
        )


    def recent_rain_inches(self, days=2):
        """
        Approximate recent rain by summing daily precipitation
        for today plus the preceding completed days.
        """

        try:
            days = int(days)
        except:
            days = 2

        if days < 1:
            days = 1

        if days > 4:
            days = 4

        records = []

        history = self.data.get(
            "history",
            []
        )

        daily = self.data.get(
            "daily",
            []
        )

        # Add prior days, then today's forecast/observed daily total.
        records.extend(history)

        if daily:
            records.append(
                daily[0]
            )

        records = records[
            -days:
        ]

        total = 0.0
        found = False

        for record in records:

            value = record.get(
                "precipitation_in"
            )

            if value is None:
                continue

            try:
                total += float(value)
                found = True
            except:
                pass

        return total if found else None


    def refresh_interval_seconds(self):

        return (
            self.refresh_minutes *
            60
        )
