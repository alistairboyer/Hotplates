from __future__ import annotations
from typing import Dict, Callable, Union, Optional, Any

from . import SerialThreadedDuplex
from .MSHProCommunication import COMMUNICATION

import logging

logger = logging.getLogger("Hotplates.MSHPro")
logger.addHandler(logging.NullHandler())


class MSHPro:
    """
    Serial communication with a MSHPro hotplate.

    """

    SERIAL_SETTINGS = {
        "baudrate": 9600,
        "bytesize": SerialThreadedDuplex.serial.EIGHTBITS,  # type: ignore
        "parity": SerialThreadedDuplex.serial.PARITY_NONE,  # type: ignore
        "stopbits": SerialThreadedDuplex.serial.STOPBITS_ONE,  # type: ignore
        "xonxoff": False,
        "rtscts": False,
        "dsrdtr": False,
    }
    """
    Communications settings for the MSHPro hotplate.
    """

    HEATLIMIT_MAX: float = 340.0
    """Maximum settable temperature (°C)."""
    HEATLIMIT_MIN: float = 25.0
    """Minimum settable temperature (°C)."""
    STIRLIMIT_MAX: int = 1500
    """Maximum settable stir speed (rpm)."""
    STIRLIMIT_MIN: int = 100
    """Minimum settable stir speed (rpm)."""

    __Serial: SerialThreadedDuplex.Serial

    def __init__(
        self,
        port: Optional[Union[int, str]] = None,
        timeout: float | int = 0.5,
    ):
        """
        Create a MSHPro object.

        The serial settings of the hotplate are stored in
        :const:`MSHPro.SERIAL_SETTINGS`.

        Args:
            port (Optional[Union[int, str]], optional):
                Serial port name.
                If an integer is passed it will be converted to
                a serial port name depending on the current system
                using :func:`.SerialThreadedDuplex.port_parser`
                The serial port will not be opened upon creation.
                Defaults to None.
            timeout (float | int, optional):
                Set the timeout for serial read.
                Passed into :class:`.SerialThreadedDuplex.Serial` creation.
                Defaults to 0.5.
        """
        # the other timeouts, not included in the SERIAL_SETTINGS, are:
        # write_timeout
        # inter_byte_timeout
        self.__Serial = SerialThreadedDuplex.Serial(
            timeout=timeout,
            **self.__class__.SERIAL_SETTINGS,
        )
        if port is not None:
            self.__Serial.port = SerialThreadedDuplex.port_parser(port)

    def __del__(self) -> None:
        self.__Serial.close()

    @property
    def port(self) -> Any:  # Returns a `property` object if not set
        """Serial port name."""
        return self.__Serial.port

    def serial_open(self) -> None:
        """Open Serial."""
        # newer versions of PySerial
        if hasattr(self.__Serial, "is_open"):
            if self.__Serial.is_open:
                return
        # older versions of PySerial
        elif hasattr(self.__Serial, "isOpen"):
            if self.__Serial.isOpen():
                return

        # Try to open port
        self.__Serial.open()

    def serial_close(self) -> None:
        """Close Serial."""
        self.__Serial.close()

    def __command(
        self,
        command: COMMUNICATION,
        var: Optional[Any] = None,
        d: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send a command to the hotplate using the
        :class:`.SerialThreadedDuplex.Serial` interface.

        Args:
            command (COMMUNICATION):
                :mod:`COMMUNICATION` to send.
            var (Optional[Any], optional):
                Value to send where appropriate.
                Defaults to None.
            d (Optional[Dict[str, Any]], optional):
                ``dict`` to update with parsed values.
                Defaults to None that gives an empty ``dict``.

        Returns:
            Dict[str, Any]: ``dict`` with parsed responses.
        """
        d = dict() if d is None else d
        self.serial_open()
        w_bytes = command.to_bytes(var)
        logger.debug("Sending bytes: {}.".format(w_bytes.hex()))
        r_bytes = self.__Serial.write_with_read(w_bytes, size=command.len_rx)
        logger.debug("Received bytes: {}.".format(r_bytes.hex()))
        d.update(command.parse_response(r_bytes))
        return d

    def ping(self) -> bool:
        """
        Send a ping command.

        Returns:
            bool: ``True`` if hotplate is online and responding correctly.
        """
        try:
            return self.__command(COMMUNICATION.PING)["success"] is True
        except Exception:
            return False

    def _status(self) -> Dict[str, Any]:
        """
        Get status of the hotplate: `stir_set`, `stir_actual`,
        `heat_set`, `heat_actual`.
        See :meth:`.status`.
        """
        return self.__command(COMMUNICATION.STATUS)

    def _info(self) -> Dict[str, Any]:
        """
        Get info from the hotplate: `mode`, `stir_on`, `heat_on`,
        `heat_limit` and `heat_alarm`.
        See :meth:`.status`.
        """
        return self.__command(COMMUNICATION.INFO)

    def status(self, raw_values: bool = False) -> Dict[str, Any]:
        """
        Get hotplate status.
        See also :meth:`._status` and :meth:`._info` for a subset of this data.

        Dictionary keys:
            -   `"success"` (`bool`): ``True`` if command received correctly.
            -   `"stir_set"` (`int` | "Off"): target speed (rpm) or "Off".
                Set :attr:`raw _values` to be ``True`` to view
                value when off instead of "Off".
            -   `"stir_actual"` (`int`): measured speed (rpm).
            -   `"heat_set"` (`float` | "Off"): target temperature (°C) or "Off".
                Set :attr:`raw _values` to be ``True`` to view value when
                off instead of "Off".
            -   `"heat_actual"` (`float`): measured temperature (°C).
                N.B. The `heat_actual` reading is from an internal temperature
                sensor that doesn't necesserily match the display value.
                If a temperature probe is attached then both
                the display and `heat_actual` reading is from the probe.
            -   `"stir_on"` (`bool`): ``True`` if stirring.
            -   `"heat_on"` (`bool`): ``True`` if heating.
            -   `"heat_limit"` (`float`): maximum set temperature (°C).
            -   `"mode"` ({"A", "B", "C"}): default is "A". **Undocumented**.
                Possibly related to heat rate profile.
            -   `"heat_alarm"`. **Undocumented**. Unknown.
                Only returned when :attr:`raw _values` is ``True``.

        Args:
            raw_values: bool
                Default behaviour [``False``] is to convert
                values to more readable format,
                specifically related to set values when off and hiding unknown values.
                If ``True`` then the raw values from
                :meth:`.COMMUNICATION.parse_response` are returned.


        Returns:
            dict: Dictionary of hotplate information.
        """
        r = self.__command(COMMUNICATION.STATUS)
        r = self.__command(COMMUNICATION.INFO, None, r)
        # parse on/off information to set values
        if not raw_values:
            if not r["heat_on"]:
                r["heat_set"] = "Off"
            if not r["stir_on"]:
                r["stir_set"] = "Off"
            # this info appears to have no value
            r["heat_alarm"]
        return r

    def __off(self, *args: COMMUNICATION) -> None:
        """
        Helper function to turn off.
        """
        current_status: Dict[str, Any]
        current_status = self.status()

        command: COMMUNICATION
        for command in args:
            name: str
            name = command.name.lower()
            # already off
            if not current_status["{}_on".format(name)]:
                logger.info("{} {} {}".format(command, "OFF", "Success [already off]"))
                continue
            # send current setting to turn off
            if self.__command(command, current_status["{}_set".format(name)])[
                "success"
            ]:
                logger.info("{} {} {}".format(command, "OFF", "Success"))
                continue
            logger.error("{} {} {}".format(command, "OFF", "ERROR!"))

    def __setval(self, command: COMMUNICATION, val: Any = None) -> bool:
        """
        Helper function to set values.
        """
        current_status = self.status(raw_values=True)
        name = command.name.lower()
        set_value = current_status["{}_set".format(name)]
        on_status = current_status["{}_on".format(name)]

        # switch on to current value
        if val is None:
            val = set_value

        # already at correct value
        if set_value == val:
            # already on
            if on_status:
                logger.info(
                    "{} {} {}".format(command, val, "Success [already at target value]")
                )
                return True
            # send same value to turn on
            if self.__command(command, set_value)["success"]:
                logger.info("{} {} {}".format(command, val, "Success [switched on]"))
                return True
            logger.error("{} {} {}".format(command, val, "ERROR!"))
            return False

        # not at correct value

        # send value once to change value
        # this will also toggle the on / off status
        if not self.__command(command, val)["success"]:
            logger.error("{} {} {}".format(command, val, "ERROR!"))
            return False

        # was not previously on - but now on with correct value
        if not on_status:
            logger.info(
                "{} {} {}".format(command, val, "Success [set value, switched on]")
            )
            return True

        # send value a second time to turn back on
        if self.__command(command, val)["success"]:
            logger.info(
                "{} {} {}".format(
                    command, val, "Success [switched off, set value, switched on]"
                )
            )
            return True

        logger.error("{} {} {}".format(command, val, "ERROR!"))
        return False

    def off(self) -> None:
        """
        Turn off stirring and heating.
        """
        self.__off(COMMUNICATION.HEAT, COMMUNICATION.STIR)

    def heat(self, val: float) -> None:
        """
        Control heating.

        If :attr:`val` is not truthy, heating will be turned off.
        If an exception is encountered, heating will be turned off.

        Args:
            val (int): Target temperature (1 decimal place float, rounded down, °C).

        Raises:
            ValueError:
                If :attr:`val` can not be converted to ``float``
                or is outside permissable range.

        """
        if not val:
            self.heat_off()
            return
        try:
            val = float(val)
            if not self.HEATLIMIT_MIN <= val <= self.HEATLIMIT_MAX:
                self.heat_off()
                raise ValueError(
                    "Heat setting {} outside allowable range {}-{}.".format(
                        val, self.HEATLIMIT_MIN, self.HEATLIMIT_MAX
                    )
                )
            self.__setval(COMMUNICATION.HEAT, val)
        except Exception as e:
            self.heat_off()
            raise e

    def heat_off(self) -> None:
        """
        Turn off heating.
        """
        self.__off(COMMUNICATION.HEAT)

    def stir(self, val: int) -> None:
        """
        Control stirring.

        If :attr:`val` is not truthy, stirring will be turned off.

        Args:
            val (int): Target stir speed (integer, rpm).

        Raises:
            ValueError:
                If :attr:`val` can not be converted to ``int``
                or is outside permissable range.

        """
        if not val:
            self.stir_off()
            return
        val = int(val)
        if not self.STIRLIMIT_MIN <= val <= self.STIRLIMIT_MAX:
            raise ValueError(
                "Stir speed setting {} outside allowable range {}-{}.".format(
                    val, self.STIRLIMIT_MIN, self.STIRLIMIT_MAX
                )
            )
        self.__setval(COMMUNICATION.STIR, val)

    def stir_off(self) -> None:
        """
        Turn off stirring.
        """
        self.__off(COMMUNICATION.STIR)

    def mode(self, mode: str) -> None:
        """
        Set hotplate mode.
        **Warning: undocumented feature.**

        Args:
            mode ({"A", "B", "C"}): Choose mode A, B or C.
        """
        target_mode = "ABC".index(mode)
        set_mode = "ABC".index(self._info()["mode"])
        for _ in range((3 + target_mode - set_mode) % 3):
            self.__command(COMMUNICATION._MODE)

    def text_command(self, cmd: str) -> Any:
        """
        Interpret a text command.
        The command is one of {"PING", "STATUS", "OFF", "STIR", "HEAT", "MODE"}.
        Text is not case-sensitive.
        Each of these will be sent to the corresponding method.
        i.e. for {"HEAT", "STIR" and "MODE"} a whitespace separated value
        will be used for setting.


        Examples:

        .. code-block:: python

            >>> hp = Hotplates.MSHPro(0)
            >>> hp.text_command("STATUS")
            >>> hp.text_command("HEAT OFF")
            >>> hp.text_command("MODE B")
            >>> hp.text_command("stir 560")
            >>> hp.text_command("PING")
            >>> hp.text_command("OFF")
        """

        cmd_dict: Dict[str, Callable]  # type: ignore
        cmd_dict = {
            "PING": self.ping,
            "STATUS": self.status,
            "OFF": self.off,
            "STIR": self.stir,
            "HEAT": self.heat,
            "MODE": self.mode,
        }
        cmds = str(cmd).upper().split()
        if cmds[0] not in cmd_dict:
            raise ValueError("Could not find command: {}".format(cmd))
        if cmds[0] in {"STIR", "HEAT", "MODE"}:
            if cmds[1] == "OFF":
                return cmd_dict[cmds[0]](False)
            return cmd_dict[cmds[0]](cmds[1])
        return cmd_dict[cmds[0]]()
