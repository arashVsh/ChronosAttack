"""Deny network connections during the offline evidence replay."""
import sys


def deny_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network access is disabled during the offline research replay")


sys.addaudithook(deny_network)
