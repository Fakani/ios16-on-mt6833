#!/usr/bin/env python3
"""Correct the v66-v69 loader ACK probe, without changing SPI setup.

Usage: patch_ilitek_ack2.py /path/to/mtkloader.c
The input must contain the historical ilitek_probe() or this exact fix.
"""
import argparse
from pathlib import Path


REPLACEMENTS = (
    ('uint8_t tx = 0x82, rx = 0;',
     'uint8_t tx[2] = { 0x82, 0x00 }, rx[2] = { 0, 0 };'),
    ('spi_xfer(&tx, &rx, 1)', 'spi_xfer(tx, rx, 2)'),
    ('out("ilitek: 0x82 -> 0x");', 'out("ilitek: ACK2 -> 0x");'),
    ('out_hex(rx);', 'out_hex(rx[1]);'),
    ('out(rx == 0xA3 ?', 'out(rx[1] == 0xA3 ?'),
)


def patch_source(source):
    start = source.find('static void ilitek_probe(void)\n{')
    if start < 0:
        raise ValueError('expected historical ilitek_probe() not found')
    end = source.find('\n}', start)
    if end < 0:
        raise ValueError('probe function terminator not found')
    end += 2
    body = source[start:end]
    if all(new in body and old not in body for old, new in REPLACEMENTS):
        return source
    for old, _ in REPLACEMENTS:
        if body.count(old) != 1:
            raise ValueError('unexpected or partially patched probe: ' + old)
    for old, new in REPLACEMENTS:
        body = body.replace(old, new, 1)
    body = body.replace(
        '\tuint8_t tx[2]',
        '\t/* One CS: command byte, then dummy byte clocks ACK into rx[1]. */\n\tuint8_t tx[2]', 1)
    return source[:start] + body + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    before = args.source.read_text()
    after = patch_source(before)
    if before == after:
        print('already patched: ACK2 (rx[1])')
        return
    backup = args.source.with_name(args.source.name + '.pre-ack2')
    if backup.exists() and backup.read_text() != before:
        raise SystemExit('backup exists with different content; keep it and use a fresh source copy')
    if not backup.exists():
        backup.write_text(before)
    args.source.write_text(after)
    print('patched ACK probe only: 16 clocks, tx={0x82,0x00}, ACK=rx[1]')


if __name__ == '__main__':
    main()
