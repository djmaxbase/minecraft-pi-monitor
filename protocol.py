"""Minecraft Java status and Query protocols. Python 3.9+, no extra packages."""
import argparse
import csv
import json
import socket
import struct
import time
from datetime import datetime
from pathlib import Path


def varint(n):
    data = bytearray()
    while True:
        b = n & 127
        n >>= 7
        data.append(b | (128 if n else 0))
        if not n:
            return bytes(data)


def read_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError('Server closed connection')
        data.extend(chunk)
    return bytes(data)


def read_varint(sock):
    result = 0
    for i in range(5):
        b = read_exact(sock, 1)[0]
        result |= (b & 127) << (7 * i)
        if not b & 128:
            return result
    raise ValueError('Invalid VarInt')


def status(host, port, connect_host=None, connect_port=None, timeout=5):
    hostname = host.encode('utf-8')
    handshake = b'\x00' + varint(754) + varint(len(hostname)) + hostname + struct.pack('>H', port) + b'\x01'
    with socket.create_connection((connect_host or host, connect_port or port), timeout=timeout) as sock:
        sock.sendall(varint(len(handshake)) + handshake + b'\x01\x00')
        length = read_varint(sock)
        if length > 2_000_000:
            raise ValueError('Oversized server response')
        # Reading from the same socket keeps framing exact.
        if read_varint(sock) != 0:
            raise ValueError('Unexpected status packet')
        size = read_varint(sock)
        if size > length:
            raise ValueError('Invalid status length')
        return json.loads(read_exact(sock, size))


def full_query(host, port, timeout=3):
    session = b'\x01\x02\x03\x04'
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.send(b'\xfe\xfd\x09' + session)
        data = sock.recv(4096)
        if data[:5] != b'\x09' + session:
            raise ValueError('Invalid Query challenge')
        token = int(data[5:].rstrip(b'\x00'))
        sock.send(b'\xfe\xfd\x00' + session + struct.pack('>i', token) + b'\x00' * 4)
        data = sock.recv(65535)
        if data[:5] != b'\x00' + session:
            raise ValueError('Invalid Query response')
        header, section = data[5:].split(b'\x00\x00\x01player_\x00\x00', 1)
        # Full stat header: splitnum NUL, split index byte, padding byte.
        fields = header[11:].split(b'\x00')
        metadata = {fields[i].decode('utf-8', errors='replace'):
                    fields[i+1].decode('utf-8', errors='replace')
                    for i in range(0, len(fields)-1, 2) if fields[i]}
        names = sorted(set(x.decode('utf-8', errors='replace')
                           for x in section.split(b'\x00') if x))
        return {'names': names, 'metadata': metadata}


def ping(host, port, timeout=5):
    """Measure status-protocol ping/pong, including a fresh connection."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        encoded = host.encode()
        handshake = b'\x00' + varint(754) + varint(len(encoded)) + encoded + struct.pack('>H', port) + b'\x01'
        sock.sendall(varint(len(handshake)) + handshake + b'\x01\x00')
        length = read_varint(sock)
        if length > 2_000_000:
            raise ValueError('Oversized response')
        read_exact(sock, length)
        payload = struct.pack('>q', time.time_ns() // 1_000_000)
        started = time.monotonic()
        sock.sendall(b'\x09\x01' + payload)
        if read_varint(sock) != 9 or read_exact(sock, 9) != b'\x01' + payload:
            raise ValueError('Invalid pong')
        return round((time.monotonic() - started) * 1000, 2)

