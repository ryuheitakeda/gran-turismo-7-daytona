# Capture the Chiaki stream window and save it as PNG, with nothing but xwd
# (x11-apps) and python3's standard library. xwd doesn't grab the X server.

import os
import struct
import subprocess
import zlib

WINDOW_NAME = os.environ.get('WINDOW_NAME', r'^Chiaki \| Stream$')


def find_window(name=WINDOW_NAME):
    out = subprocess.run(['xdotool', 'search', '--name', name], capture_output=True, text=True).stdout
    if not out.split():
        raise RuntimeError('no window matches %r' % name)
    return int(out.split()[0])


def capture(window):
    """The window's image now, as (width, height, RGB bytes)."""
    data = subprocess.run(['xwd', '-silent', '-id', str(window)], capture_output=True,
                          check=True, timeout=10).stdout
    h = struct.unpack_from('>25I', data, 0)  # XWDFileHeader, always big-endian
    header_size, version, pixmap_format, width, height = h[0], h[1], h[2], h[4], h[5]
    byte_order, bits_per_pixel, bytes_per_line, ncolors = h[7], h[11], h[12], h[19]
    if version != 7 or pixmap_format != 2 or bits_per_pixel != 32:
        raise RuntimeError('unsupported xwd image (version %d, format %d, %d bpp)'
                           % (version, pixmap_format, bits_per_pixel))
    start = header_size + ncolors * 12
    pixels = data[start:start + bytes_per_line * height]
    if bytes_per_line != width * 4:
        pixels = b''.join(pixels[y * bytes_per_line:y * bytes_per_line + width * 4]
                          for y in range(height))
    r, g, b = (2, 1, 0) if byte_order == 0 else (1, 2, 3)  # BGRX or XRGB in memory
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = pixels[r::4], pixels[g::4], pixels[b::4]
    return width, height, bytes(rgb)


def png(width, height, rgb):
    stride = width * 3
    raw = b''.join(b'\0' + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def save_png(path, width, height, rgb):
    with open(path + '.tmp', 'wb') as f:
        f.write(png(width, height, rgb))
    os.replace(path + '.tmp', path)
