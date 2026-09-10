"""Generate web/helmet.png - a football helmet - with no image libraries.

Everything is drawn by testing each pixel against a few ellipses and capsules,
so this needs nothing installed. Shapes are described in 0..1 coordinates and
scaled up, which keeps them readable while tweaking.
"""

import struct
import zlib

SIZE = 512
SS = 2  # Supersampling factor; edges are averaged down for smoothness.

BG = (15, 17, 21)
SHELL = (52, 209, 124)
SHELL_DARK = (30, 150, 88)
MASK = (228, 234, 240)
HOLE = (18, 40, 28)


def _chunk(tag, data):
    payload = tag + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def _ellipse(u, v, cu, cv, ru, rv):
    du, dv = (u - cu) / ru, (v - cv) / rv
    return du * du + dv * dv <= 1.0


def _capsule(u, v, u0, v0, u1, v1, radius):
    """Distance test against a thick line segment - used for the face mask."""
    dx, dy = u1 - u0, v1 - v0
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else ((u - u0) * dx + (v - v0) * dy) / length
    t = max(0.0, min(1.0, t))
    px, py = u0 + t * dx, v0 + t * dy
    return (u - px) ** 2 + (v - py) ** 2 <= radius * radius


def _shade(v):
    """Blend the shell colour top-to-bottom so the dome reads as curved."""
    k = max(0.0, min(1.0, (v - 0.20) / 0.55))
    return tuple(int(SHELL[i] + (SHELL_DARK[i] - SHELL[i]) * k) for i in range(3))


def _sample(u, v):
    # Face mask sits in front of everything else. The bars start back under the
    # shell edge so they read as bolted on rather than floating.
    mask = (_capsule(u, v, 0.560, 0.590, 0.870, 0.600, 0.027)
            or _capsule(u, v, 0.545, 0.700, 0.860, 0.688, 0.027)
            or _capsule(u, v, 0.862, 0.572, 0.855, 0.712, 0.027))

    dome = _ellipse(u, v, 0.460, 0.445, 0.305, 0.295)
    jaw = _ellipse(u, v, 0.440, 0.580, 0.268, 0.245)
    opening = _ellipse(u, v, 0.800, 0.620, 0.190, 0.170)

    shell = (dome or jaw) and not opening

    if mask:
        return MASK
    if shell:
        if _ellipse(u, v, 0.395, 0.525, 0.058, 0.058):
            return HOLE  # Ear hole.
        return _shade(v)
    return BG


def build():
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)  # PNG filter byte: none
        for x in range(SIZE):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    u = (x + (sx + 0.5) / SS) / SIZE
                    v = (y + (sy + 0.5) / SS) / SIZE
                    cr, cg, cb = _sample(u, v)
                    r += cr
                    g += cg
                    b += cb
            n = SS * SS
            rows += bytes((r // n, g // n, b // n))

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += _chunk(b"IEND", b"")
    return png


if __name__ == "__main__":
    with open("web/helmet.png", "wb") as handle:
        handle.write(build())
    print("wrote web/helmet.png")
