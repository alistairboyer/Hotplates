from __future__ import annotations
from typing import Dict, Iterable, Optional, Any

import enum


class COMMUNICATION(enum.Enum):
    """
    Utilities for serial communication with a MSHPro hotplate.
    Contains all information about communication protocols, including
    functions for encoding and decoding.

    Communications available with the hotplate:

    -   :const:`COMMUNICATION.PING`
        Ping command to see if the hotplate is on and responding correctly.
    -   :const:`COMMUNICATION.INFO`
        Get info from the hotplate: `mode`, `stir_on`, `heat_on`, `heat_limit`
        and `heat_alarm`.
    -   :const:`COMMUNICATION.STATUS`
        Get status of the hotplate: `stir_set`, `stir_actual`, `heat_set`
        and `heat_actual`.
        N.B. The `heat_actual` reading is from an internal
        temperature sensor that doesn't necesserily match the display value.
        If a temperature probe is attached then both the display and `heat_actual`
        reading is from the probe.
    -   :const:`COMMUNICATION.STIR`
        Set stirring speed (rpm).
        Use :meth:`to_bytes` with ``val = stir_set`` (int).
        Sending speed toggles on or off.
    -   :const:`COMMUNICATION.HEAT`
        Set temperature (°C).
        Use :meth:`to_bytes` with ``val = heat_set``
        (1 decimal place float, rounded down).
        Sending set temperature toggles on or off.

    .. warning::

        Communication values below this,
        prefixed with a single underscore,
        are undocumented.
        Proceed with extreme caution!

    -   :const:`COMMUNICATION._MODE`
        The hotplate default mode is "A".
        This command toggles between ["A", "B", "C"] modes.
        The mode is beleived to be heating profiles,
        i.e. "A" will get to the target temperature fastest but may overshoot,
        "C" will try to avoid overshooting; and "B" is a balance between the two.


    Example usage:

    ::

        import Hotplates.MSHProCommunication
        comm = Hotplates.MSHProCommunication.COMMUNICATION.PING
        comm.to_bytes()
        >> b'\\xfe\\xa0\\x00\\x00\\x00\\xa0'
        comm.len_rx
        >> 6

    """

    PING = 0xA0
    INFO = 0xA1
    STATUS = 0xA2
    STIR = 0xB1
    HEAT = 0xB2
    _MODE = 0xB3

    # Unknown commands that seem to promote response
    # WARNING! Using these can DESTROY the hotplate!!
    # 0xA3 - Firmware info???
    # 0xA4
    # 0xB4
    # 0xB5
    # 0xB7

    @property
    def len_rx(self) -> int:
        """
        Length of expected response.
        """
        if self in {COMMUNICATION.INFO, COMMUNICATION.STATUS}:
            return 11
        return 6

    def to_bytes(self, val: Optional[Any] = None) -> bytes:
        """
        Generate ``bytes`` for transmission to hotplate.

        Args:
            val (int | float, optional):
                Value for setting where appropriate
                (i.e. :const:`COMMUNICATION.STIR`, :const:`COMMUNICATION.HEAT`).

        Returns:
            bytes : bytes for transmission.

        Raises:
            ValueError:
                When :attr:`val` is incorectly formatted
                or outside of allowed range.
        """
        if self == COMMUNICATION.PING:
            return b"\xfe\xa0\x00\x00\x00\xa0"

        if self == COMMUNICATION.INFO:
            return b"\xfe\xa1\x00\x00\x00\xa1"

        if self == COMMUNICATION.STATUS:
            return b"\xfe\xa2\x00\x00\x00\xa2"

        if self == COMMUNICATION._MODE:
            return b"\xfe\xb3\x00\x00\x00\xb3"

        # need a value
        if val is None:
            raise ValueError("Please supply value.")

        # Format value and check within limits
        if self == COMMUNICATION.STIR:
            val = int(val)

        # Format value and check within limits
        if self == COMMUNICATION.HEAT:
            # Temperature setting in 0.1 degree increments
            # multiplied by 10 to convert to int
            val = int(float(val) * 10)

        # unsigned 2 bytes
        if not 0 <= val <= 65535:
            raise ValueError("Value outside maximum range.")

        # Encode value and perform checksum
        encoded_value: bytes = bytes((self.value, (val >> 8) & 0xFF, val & 0xFF))
        return bytes(
            (
                0xFE,
                *encoded_value,
                0x00,
                checksum(encoded_value),
            )
        )

    def parse_response(self, b: bytes) -> Dict[str, Any]:
        """
        Process ``bytes`` received from serial communication
        with hotplate.

        Args:
            b (bytes): ``bytes`` for decoding.

        Returns:
            dict[str, Any]:
                Parsed reponses.
                All responses have a key ``"success": bool`` that
                represents the overall outcome.
                ``INFO`` and ``STATUS`` responses have keys
                referencing data as described above.

        Raises:
            IncompleteResponseException : on communications timeout.
            ResponseFormatException: on error with checksum or control bytes.
            HotplateException: if an error is sent from the hotplate.
            ResponseParseException: if there was a problem parsing data.

        """
        response: Dict[str, Any]
        response = {"success": False}

        # check response format
        if len(b) < self.len_rx:  # length check
            raise IncompleteResponseException()
        if not (
            b[0] == 0xFD  # received data flag
            and b[1] == self.value  # received data type flag
            and b[-1] == checksum(b[1:-1])  # checksum
        ):
            raise ResponseFormatException(
                "Command {}, invalid response: {!r}".format(self, b)
            )

        # checks are complete so only need the data part of the reply
        b_data = b[2:-1]

        # these commands have similar response structure
        if self in {
            COMMUNICATION.PING,
            COMMUNICATION.STIR,
            COMMUNICATION.HEAT,
            COMMUNICATION._MODE,
        }:
            # expected response on success
            if b_data == b"\x00\x00\x00":
                response["success"] = True
            # expected response on failure
            # not for PING - can't really fail at hotplate
            elif b_data == b"\x01\x00\x00" and not self == COMMUNICATION.PING:
                raise HotplateException("Hotplate error with command: {}".format(self))
            # error in received data
            else:
                raise ResponseParseException(
                    "Command {}, invalid response: {!r}".format(self, b)
                )

        if self == COMMUNICATION.INFO:
            try:
                response["mode"] = "_ABC"[b_data[0]]  # mode is 1=A, 2=B, 3=C
                response["stir_on"] = not b_data[1]
                response["heat_on"] = not b_data[2]
                response["heat_limit"] = float((b_data[3] << 8) + b_data[4]) / 10.0
                response["heat_alarm"] = not b_data[5]
                response["success"] = True
            except Exception:
                raise ResponseParseException(
                    "Command {}, invalid response: {!r}".format(self, b)
                )

        if self == COMMUNICATION.STATUS:
            try:
                # could use int.from_bytes(b_data[0:2], byteorder="big") but same speed
                response["stir_set"] = int((b_data[0] << 8) + b_data[1])
                response["stir_actual"] = int((b_data[2] << 8) + b_data[3])
                response["heat_set"] = float((b_data[4] << 8) + b_data[5]) / 10.0
                response["heat_actual"] = float((b_data[6] << 8) + b_data[7]) / 10.0
                response["success"] = True
            except Exception:
                raise ResponseParseException(
                    "Command {}, invalid response: {!r}".format(self, b)
                )

        return response


class COMMUNICATIONException(Exception):
    """Base exception for exceptions that could
    be encountered using :mod:`COMMUNICATION`."""


class IncompleteResponseException(COMMUNICATIONException):
    """Not enough bytes received before timeout."""


class ResponseFormatException(COMMUNICATIONException):
    """Error with response bytes or checksum."""


class ResponseParseException(COMMUNICATIONException):
    """Error parsing :mod:`COMMUNICATION` response."""


class HotplateException(COMMUNICATIONException):
    """Hotplate indicated error."""


def checksum(val: Iterable[int] | str) -> int:
    """
    Checksum calculator for MSHPro communication.

    Sum bytes discarding overflow.

    Args:
        val (Iterable[int] | str) : Value for checksum calculation.

    Returns:
        int : 1 byte checksum.
    """
    checksum_result: int = 0
    if type(val) is str:
        val = map(ord, val)
    for c in val:
        checksum_result = (checksum_result + int(c)) & 0xFF
    return checksum_result
