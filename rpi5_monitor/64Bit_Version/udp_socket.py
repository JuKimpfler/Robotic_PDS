"""
udp_socket.py — gemeinsamer Aufbau der UDP-Empfangssockets
=============================================================
Alle drei Empfaengerprozesse (Telemetrie, Deskriptor, Aux-Uplink) oeffnen
ihren Port hier.

Bewusst OHNE SO_REUSEADDR: unter Linux duerfen damit zwei Prozesse
denselben UDP-Port binden, und Unicast-Pakete gehen dann nur noch an den
zuletzt gebundenen. Eine versehentlich zweimal gestartete GUI (Autostart
plus Handstart) hat der ersten so still die komplette Telemetrie
weggenommen — die Meldung "Port belegt" kam nie. Unter Windows erlaubt die
Option sogar das Uebernehmen eines fremden Ports. Gebraucht wurde sie nie:
UDP kennt kein TIME_WAIT, ein neu gestarteter Prozess bekommt den Port
sofort wieder.
"""
from __future__ import annotations

import socket


def open_udp_receiver(port: int, *, rcvbuf: int | None = None,
                      timeout: float = 0.5) -> socket.socket:
    """UDP-Socket an 0.0.0.0:port binden.

    timeout: damit die Empfangsschleife regelmaessig ihr stop_event prueft.
    Wirft OSError, wenn der Port belegt ist (dann laeuft die GUI meist schon
    einmal).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if rcvbuf:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(timeout)
    except OSError:
        sock.close()
        raise
    return sock
