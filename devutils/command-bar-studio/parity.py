#!/usr/bin/env python3
"""Compare native captures and geometry; report repeat noise separately."""
import argparse
import json
import os
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
import struct
import zlib


def png(path, with_profile=False):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError(f'Not PNG: {path}')
    compressed = bytearray(); cursor = 8; profile = {}
    while cursor < len(data):
        size = int.from_bytes(data[cursor:cursor+4], 'big'); kind = data[cursor+4:cursor+8]
        body = data[cursor+8:cursor+8+size]; cursor += size + 12
        if kind == b'IHDR': width, height, depth, color, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT': compressed.extend(body)
        elif kind in (b'iCCP', b'sRGB', b'gAMA', b'cHRM', b'cICP'): profile[kind] = body
    if depth != 8 or color not in (2, 6) or interlace:
        raise ValueError(f'Unsupported PNG format {depth}/{color}/{interlace}: {path}')
    channels = {2: 3, 6: 4}[color]; stride = width * channels
    raw = zlib.decompress(compressed); previous = bytearray(stride); pixels = bytearray()
    for y in range(height):
        offset = y * (stride + 1); mode = raw[offset]; row = bytearray(raw[offset+1:offset+1+stride])
        for x in range(stride):
            left = row[x-channels] if x >= channels else 0; above = previous[x]
            upper_left = previous[x-channels] if x >= channels else 0
            if mode == 1: prediction = left
            elif mode == 2: prediction = above
            elif mode == 3: prediction = (left + above) // 2
            elif mode == 4:
                p = left + above - upper_left
                distances = [abs(p-left), abs(p-above), abs(p-upper_left)]
                prediction = [left, above, upper_left][distances.index(min(distances))]
            elif mode == 0: prediction = 0
            else: raise ValueError(f'Unknown PNG filter {mode}')
            row[x] = (row[x] + prediction) & 255
        if channels == 4: pixels.extend(row)
        else:
            for x in range(0, len(row), 3): pixels.extend((*row[x:x+3], 255))
        previous = row
    return ((width, height), pixels, profile) if with_profile else ((width, height), pixels)


def difference(first, second, backdrop=(43, 51, 69)):
    size, left, profile = png(first, True); other_size, right, other_profile = png(second, True)
    if profile != other_profile: raise ValueError('PNG color profiles differ; capture in the same color context')
    if size != other_size: return {'same_size': False, 'sizes': [size, other_size]}
    histogram = [0] * 256; alpha_histogram = [0] * 256; rgb_error = 0
    for offset in range(0, len(left), 4):
        a_alpha = left[offset+3]; b_alpha = right[offset+3]
        alpha_histogram[abs(a_alpha-b_alpha)] += 1
        for channel in range(3):
            a = left[offset+channel]; b = right[offset+channel]; background = backdrop[channel]
            rgb_error += abs(a-b)
            a_composite = (a*a_alpha + background*(255-a_alpha) + 127) // 255
            b_composite = (b*b_alpha + background*(255-b_alpha) + 127) // 255
            histogram[abs(a_composite-b_composite)] += 1
    count = sum(histogram); running = 0; p99 = 0
    for delta, frequency in enumerate(histogram):
        running += frequency
        if running >= count * .99: p99 = delta; break
    return {'same_size': True, 'mean_channel_error': round(sum(i*n for i,n in enumerate(histogram)) / count, 5),
            'mean_raw_rgb_error': round(rgb_error / count, 5),
            'mean_alpha_error': round(sum(i*n for i,n in enumerate(alpha_histogram)) / sum(alpha_histogram), 5),
            'fraction_alpha_over_3': round(sum(alpha_histogram[4:]) / sum(alpha_histogram), 6),
            'fraction_channels_over_3': round(sum(histogram[4:]) / count, 6), 'p99_channel_error': p99}


def native_differences(browser, studio, cases):
    source = Path(__file__).with_name('parity_native.swift')
    cache = source.parent / '.build/parity'; cache.mkdir(parents=True, exist_ok=True)
    executable = cache / hashlib.sha256(source.read_bytes()).hexdigest()
    if not executable.exists():
        env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(cache / 'module-cache'), SWIFTPM_MODULECACHE_OVERRIDE=str(cache / 'module-cache'))
        subprocess.run(['xcrun','swiftc','-O','-module-cache-path',cache / 'module-cache',source,'-lz','-o',executable], check=True, env=env)
    jobs = [{'name': name, 'left': str(browser / (name+'.png')), 'right': str(studio / (name+'.png')),
             'left_repeat': str(browser / (name+'-repeat.png')), 'right_repeat': str(studio / (name+'-repeat.png')),
             'backdrop': case.get('backdrop_rgb', [43,51,69])} for name, case in cases.items()]
    with tempfile.TemporaryDirectory(prefix='arcium-parity-', dir=cache) as temporary:
        input_path = Path(temporary)/'input.json'; output_path = Path(temporary)/'output.json'
        input_path.write_text(json.dumps(jobs)); subprocess.run([executable,input_path,output_path],check=True)
        return json.loads(output_path.read_text())


def compare(browser, studio):
    left = {case['name']: case for case in json.loads((browser / 'report.json').read_text())['cases']}
    right = {case['name']: case for case in json.loads((studio / 'report.json').read_text())['cases']}
    measured = native_differences(browser, studio, {name: left[name] for name in left.keys() & right.keys()}) if sys.platform == 'darwin' else {}
    cases = []
    for name in sorted(left.keys() | right.keys()):
        if name not in left or name not in right:
            cases.append({'name': name, 'missing': True}); continue
        geometry = {key: [left[name].get(key), right[name].get(key)]
                    for key in ('width', 'height', 'rows', 'scope', 'input', 'body', 'scopes', 'material_backend')
                    if left[name].get(key) != right[name].get(key)}
        backdrop = tuple(left[name].get('backdrop_rgb', (43, 51, 69)))
        if name in measured:
            cross = measured[name]['cross_host']; browser_noise = measured[name]['browser_repeat_noise']; studio_noise = measured[name]['studio_repeat_noise']
        else:
            cross = difference(browser / (name + '.png'), studio / (name + '.png'), backdrop)
            browser_noise = difference(browser / (name + '.png'), browser / (name + '-repeat.png'), backdrop)
            studio_noise = difference(studio / (name + '.png'), studio / (name + '-repeat.png'), backdrop)
        noise = max(item.get('mean_channel_error', 0) for item in (browser_noise, studio_noise))
        cases.append({'name': name, 'geometry_differences': geometry, 'cross_host': cross,
                      'browser_repeat_noise': browser_noise, 'studio_repeat_noise': studio_noise,
                      'cross_alpha_above_repeat_noise': round(max(0, cross.get('mean_alpha_error', 255) - max(item.get('mean_alpha_error', 0) for item in (browser_noise, studio_noise))), 5),
                      'cross_error_above_repeat_noise': round(max(0, cross.get('mean_channel_error', 255) - noise), 5)})
    # No screenshot masks or automatic tolerance inflation. A reviewer must assess
    # nonzero cross-host errors against repeat noise and inspect systematic drift.
    return {'geometry_equal': all(not case.get('geometry_differences') and not case.get('missing') for case in cases),
            'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('browser', type=Path); parser.add_argument('studio', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report = compare(args.browser, args.studio)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'geometry_equal': report['geometry_equal'], 'cases': len(report['cases']),
                      'max_alpha_error_above_repeat_noise': max(case.get('cross_alpha_above_repeat_noise', 255) for case in report['cases']),
                      'max_error_above_repeat_noise': max(case.get('cross_error_above_repeat_noise', 255) for case in report['cases'])}))


if __name__ == '__main__': main()
