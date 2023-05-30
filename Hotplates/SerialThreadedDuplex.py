from __future__ import annotations
from typing import Any, Optional, Callable

import threading
import sys
import os

import serial  # type: ignore


class Serial(serial.Serial):  # type: ignore
    """
    Extending PySerial :mod:`serial.Serial`
    to include full duplex commuication
    using :mod:`threading.Thread`.

    Example usage:

    .. code-block:: python

        >>> import Hotplates.SerialThreadedDuplex
        >>> s = Hotplates.SerialThreadedDuplex.Serial(port="/dev/ttyUSB0", timeout=1.0)
        >>> s.write_with_read_until(b"Hello!", expected="\\n")
        >>> s.value  
        # received bytes

    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        All paramaters are passed to PySerial's :mod:`serial.Serial`.
        """
        self.__rx_thread: Optional[threading.Thread] = None
        self.__rx_value: Optional[bytes] = None
        self.__rx_exception: Optional[Exception] = None
        super().__init__(*args, **kwargs)

    # method passed to threading.Thread for threaded execution
    def __read_thread(
        self,
        fn: Callable[[Any], Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        try:
            self.reset_input_buffer()
            self.__rx_value = b""
            self.__rx_value = fn(*args, **kwargs)
        except Exception as e:
            self.__rx_value = None
            self.__rx_exception = e

    def __write_with_function(
        self,
        data: bytes,
        fn: Callable[[Any], Any],
        *args: Any,
        **kwargs: Any,
    ) -> bytes:
        # check that previous thread has finished
        if self.__rx_thread is not None and self.__rx_thread.is_alive():
            raise Exception("Rx thread already started.")

        # initialise variables
        self.__rx_value = None
        self.__rx_exception = None
        try:
            # flush
            self.reset_output_buffer()
            # setup read thread
            self.__rx_thread = threading.Thread(
                target=self.__read_thread, args=(fn,) + args, kwargs=kwargs
            )
            self.__rx_thread.start()
            # write data
            self.write(data)
            # join the read thread
            self.__rx_thread.join()
        # Catch exception and store in class variable
        except Exception as e:
            # join the read thread
            # self.__rx_thread.join()
            self.__rx_value = None
            self.__rx_exception = e
        # Any exceptions will be raised when value is accessed
        return self.value

    def write_with_read_until(
        self,
        data: bytes,
        *,
        expected: str = "\n",
        size: Optional[int] = None,
    ) -> bytes:
        """
        Write data to the serial port using :meth:`serial.Serial.write`
        while reading with :meth:`serial.Serial.read_until`.

        Args:
            data (bytes):
                :attr:`data` for :meth:`serial.Serial.write`.
            expected (str, optional):
                :attr:`expected` for :meth:`serial.Serial.read_until`.
                Defaults to "\\\\n".
            size (int, optional):
                :attr:`size` for :meth:`serial.Serial.read_until`.
                Defaults to ``None``.

        Returns:
            bytes: received bytes. Also accessable using the :attr:`value` property.
        """
        return self.__write_with_function(
            data,
            self.read_until,
            expected=expected,
            size=size,
        )

    def write_with_read(
        self,
        data: bytes,
        size: int = 1,
    ) -> bytes:
        """
        Write data to the serial port using :meth:`serial.Serial.write`
        while reading with :meth:`serial.Serial.read`.

        Args:
            data (bytes): data for :meth:`serial.Serial.write`.
            size (int, optional): :attr:`size` for :meth:`serial.Serial.read`.

        Returns:
            bytes: received bytes. Also accessable using the :attr:`value` property.
        """
        return self.__write_with_function(
            data,
            self.read,
            size=size,
        )

    @property
    def value(self) -> bytes:
        """
        Most recent received value.

        Raises:
            Exception:
                If an exception was raised during operation.
                See :meth:`exception`.
            ReadingNotCompleteException:
                If the read thread is still active.
            NoCommunicationException:
                If communication was not attempted before reading value.
            NoDataException:
                If there is no data, `i.e.` device timeout.

        Returns:
            bytes: received value.
        """
        self.exception()
        if self.__rx_thread is not None and self.__rx_thread.is_alive():
            raise ReadingNotCompleteException(
                "Reading must be complete before accessing value."
            )
        if self.__rx_value is None:
            raise NoCommunicationException("Communication not started.")
        if not self.__rx_value:
            raise NoDataException("No received data.")
        return self.__rx_value

    def exception(self) -> None:
        """
        Raise any exception encountered during the process.
        """
        if self.__rx_exception:
            raise self.__rx_exception


def port_parser(
    port: int | str,
    check_exists: bool = True,
) -> str:
    """
    Parses serial port information.

    If an ``int`` is passed then a formatted ``str`` of COM{}
    or \\\\dev\\\\ttyUSB{} will be generated.

    If :attr:`check_exists` is ``True``
    the  an exception will be raised
    if the port can not be found.


    Args:
        port (int | str): port name for parsing.
        check_exists (bool, optional): Check if port exists. Defaults to ``True``.

    Raises:
        PortNotFoundException: If the port is not found.

    Returns:
        str: parsed port name.
    """
    try:
        # if an integer is passed then try to convert
        # it to a str depending on the current os
        port = int(port)
        if "win" in sys.platform:
            port = "COM{}".format(port)
        else:
            port = "/dev/ttyUSB{}".format(port)
    except ValueError:
        port = str(port)
    if check_exists and not os.path.exists(port):
        raise PortNotFoundException("Port does not exist: {}.".format(port))
    return port


class SerialException(Exception):
    """Base exception for serial exceptions."""


class NoCommunicationException(SerialException):
    """No communication attempted."""


class NoDataException(SerialException):
    """No data received."""


class ReadingNotCompleteException(SerialException):
    """Thread not completed."""


class PortNotFoundException(Exception):
    """Port not found on system."""
