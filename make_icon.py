"""Generate web/icon.png with no image libraries.

The icon is a football split green-to-red through a yellow seam, which is the
same colour language the report itself uses.
"""

import struct
import zlib

SIZE = 512


def _chunk(tag, data):
    payload = tag + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def build():
    cx = cy = SIZE / 2.0
    a, b = SIZE * 0.42, SIZE * 0.26  # Football is wider than it is tall.

    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)  # PNG filter byte: none
        for x in range(SIZE):
            nx, ny = (x - cx) / a, (y - cy) / b
            dist = nx * nx + ny * ny
            if dist <= 1.0:
                # Blend green -> yellow -> red left to right.
                t = min(1.0, max(0.0, (x - (cx - a)) / (2 * a)))
                if t < 0.5:
                    k = t / 0.5
                    r, g, bl = int(52 + (255 - 52) * k), int(209 + (197 - 209) * k), int(124 + (49 - 124) * k)
                else:
                    k = (t - 0.5) / 0.5
                    r, g, bl = 255, int(197 + (95 - 197) * k), int(49 + (109 - 49) * k)
                if dist > 0.86:  # Soft dark rim so the shape reads on any background.
                    r, g, bl = int(r * 0.55), int(g * 0.55), int(bl * 0.55)
                rows += bytes((r, g, bl))
            else:
                rows += bytes((15, 17, 21))

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += _chunk(b"IEND", b"")
    return png


if __name__ == "__main__":
    with open("web/icon.png", "wb") as handle:
        handle.write(build())
    print("wrote web/icon.png")
