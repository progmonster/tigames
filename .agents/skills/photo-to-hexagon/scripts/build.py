#!/usr/bin/env python3
"""Line-art → true vector → fitted physical hexagon → square A4 cards.

The photo-to-illustration stage is performed by the agent with an image tool.
This script only accepts an already prepared/approved contour illustration.
"""
from __future__ import annotations

import argparse
import copy
import ctypes.util
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageOps
from scipy.optimize import linprog, minimize_scalar
from scipy.spatial import ConvexHull
from svgpathtools import parse_path, Line, CubicBezier, QuadraticBezier
import vtracer

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
COS30 = math.sqrt(3) / 2
MM_PT = 72 / 25.4


def cairo_renderer():
    """Find an existing Homebrew Cairo without changing user configuration."""
    original = ctypes.util.find_library
    candidates = [Path('/opt/homebrew/lib/libcairo.2.dylib'),
                  Path('/usr/local/lib/libcairo.2.dylib')]
    found = next((str(p) for p in candidates if p.exists()), None)
    if found:
        def find(name):
            return found if name in ('cairo', 'cairo-2', 'libcairo-2') else original(name)
        ctypes.util.find_library = find
    try:
        import cairosvg
        return cairosvg
    except OSError as exc:
        raise RuntimeError('CairoSVG requires the system Cairo library. Install Cairo '
                           'from your standard package manager, then retry.') from exc
    finally:
        ctypes.util.find_library = original


def prepare_png(source: Path, destination: Path, threshold: float):
    im = ImageOps.exif_transpose(Image.open(source)).convert('RGBA')
    if im.width * im.height > 80_000_000:
        raise ValueError('Input exceeds 80 megapixels; supply a smaller contour image.')
    rgba = np.asarray(im)
    # The darkest channel preserves bright yellow/cyan contours as well as black.
    # White-filled holes have zero ink strength even when their alpha is opaque.
    strength = (rgba[:, :, 3] / 255) * (1 - rgba[:, :, :3].min(axis=2) / 255)
    ink = strength >= threshold
    if not ink.any():
        raise ValueError('No contours found. Supply a contour image or adjust --ink-threshold.')
    result = np.zeros_like(rgba)
    result[:, :, 3] = ink.astype(np.uint8) * 255
    Image.fromarray(result).save(destination, optimize=True)
    return ink


def flatten_controls(controls: np.ndarray, tolerance: float, depth=0):
    """Bezier's convex hull bounds the error of its chord approximation."""
    p, q = controls[0], controls[-1]
    chord = q - p
    denom = float(chord @ chord)
    if denom:
        ts = np.clip(((controls - p) @ chord) / denom, 0, 1)
        distances = np.linalg.norm(controls - (p + ts[:, None] * chord), axis=1)
    else:
        distances = np.linalg.norm(controls - p, axis=1)
    if distances.max() <= tolerance:
        return np.array([p, q])
    if depth >= 24:
        raise RuntimeError('Bezier flattening did not reach its error bound.')
    levels = [controls]
    while len(levels[-1]) > 1:
        levels.append((levels[-1][:-1] + levels[-1][1:]) / 2)
    left = np.array([level[0] for level in levels])
    right = np.array([level[-1] for level in reversed(levels)])
    return np.concatenate((flatten_controls(left, tolerance, depth + 1)[:-1],
                           flatten_controls(right, tolerance, depth + 1)))


def vector_geometry(root, tolerance):
    all_points = []
    for node in root.findall(f'{{{NS}}}path'):
        transform = node.get('transform', '')
        if transform:
            match = re.fullmatch(r'translate\(\s*([-+\d.eE]+)[, ]+([-+\d.eE]+)\s*\)', transform)
            if not match:
                raise ValueError(f'Unsupported tracing transform: {transform}')
            shift = np.array(list(map(float, match.groups())))
        else:
            shift = np.zeros(2)
        for segment in parse_path(node.get('d', '')):
            if not isinstance(segment, (Line, CubicBezier, QuadraticBezier)):
                raise ValueError('Unexpected non-Bezier segment from tracer.')
            controls = np.array([[z.real, z.imag] for z in segment.bpoints()])
            all_points.append(flatten_controls(controls, tolerance) + shift)
    if not all_points:
        raise ValueError('Tracer returned no vector geometry.')
    points = np.concatenate(all_points)
    hull = ConvexHull(points)
    return points, points[hull.vertices]


def fit_regular_hexagon(hull, angle_step_deg=0.5):
    """Optimize center/apothem for every angle, then refine good angular minima."""
    def at_angle(theta):
        angles = theta + np.arange(6) * math.pi / 3
        normals = np.column_stack((np.cos(angles), np.sin(angles)))
        support = (normals @ hull.T).max(axis=1)
        constraints = np.column_stack((-normals, -np.ones(6)))
        result = linprog([0, 0, 1], A_ub=constraints, b_ub=-support,
                         bounds=[(None, None), (None, None), (0, None)], method='highs')
        if not result.success:
            raise RuntimeError(f'Hexagon optimization failed: {result.message}')
        return float(result.x[2]), result.x[:2], float(theta % (math.pi / 3))

    step = math.radians(angle_step_deg)
    angles = np.arange(0, math.pi / 3, step)
    trials = [at_angle(theta) for theta in angles]
    candidates = sorted(trials, key=lambda x: x[0])[:8]
    refined = []
    for _, _, theta in candidates:
        answer = minimize_scalar(lambda t: at_angle(t)[0],
                                 bounds=(theta - step, theta + step), method='bounded',
                                 options={'xatol': 1e-8})
        refined.append(at_angle(answer.x))
    radius, center, theta = min(trials + refined, key=lambda x: x[0])
    return {'apothem': radius, 'center': center, 'angle': theta,
            'method': 'angular grid plus LP center/apothem and local refinement',
            'exact_global_minimum_proven': False, 'angle_step_deg': angle_step_deg}


def hex_vertices(apothem, theta):
    angles = theta + math.pi / 6 + np.arange(6) * math.pi / 3
    return apothem / COS30 * np.column_stack((np.cos(angles), np.sin(angles)))


def build_svg(traced, hull, fit, size_mm, measure, border_mm, clearance_mm, tolerance):
    outer_a = size_mm / 2 if measure == 'across-flats' else size_mm * COS30 / 2
    inner_a = outer_a - border_mm
    available = inner_a - clearance_mm
    if available <= 0:
        raise ValueError('Requested hexagon is too small for its border and clearance.')
    source_a = fit['apothem'] + tolerance
    scale = available / source_a
    theta = fit['angle']
    outer = hex_vertices(outer_a, theta)
    # Tiny canvas safety margin is not included in the requested frame measurement.
    canvas_pad = 0.002
    origin = -outer.min(axis=0) + canvas_pad
    width, height = outer.max(axis=0) - outer.min(axis=0) + 2 * canvas_pad
    root = ET.Element(f'{{{NS}}}svg', {'version': '1.1', 'width': f'{width:.9f}mm',
                      'height': f'{height:.9f}mm', 'viewBox': f'0 0 {width:.9f} {height:.9f}'})
    ET.SubElement(root, f'{{{NS}}}title').text = 'Technical model in a fitted regular hexagon'
    center = fit['center']
    translate = origin - scale * center
    model = ET.SubElement(root, f'{{{NS}}}g', {'id': 'model-outline',
                          'transform': f'matrix({scale:.12f} 0 0 {scale:.12f} '
                                       f'{translate[0]:.12f} {translate[1]:.12f})'})
    for node in traced.findall(f'{{{NS}}}path'):
        path = copy.deepcopy(node)
        path.set('fill', '#000000')
        path.set('fill-rule', 'evenodd')
        model.append(path)
    frame = ET.SubElement(root, f'{{{NS}}}g', {'id': 'enclosing-hexagon'})
    path_vertices = hex_vertices(outer_a - border_mm / 2, theta) + origin
    ET.SubElement(frame, f'{{{NS}}}polygon', {
        'points': ' '.join(f'{x:.10f},{y:.10f}' for x, y in path_vertices),
        'fill': 'none', 'stroke': '#000000', 'stroke-width': f'{border_mm:.10f}',
        'stroke-linejoin': 'miter', 'stroke-miterlimit': '4'})
    normals = np.column_stack((np.cos(theta + np.arange(6) * math.pi / 3),
                               np.sin(theta + np.arange(6) * math.pi / 3)))
    model_hull_mm = (hull - center) * scale
    # Chord error bounds also cover parts of the Bezier curves between samples.
    max_support = float((normals @ model_hull_mm.T).max()) + tolerance * scale
    if max_support > inner_a - clearance_mm + 1e-7:
        raise RuntimeError('Model failed containment check; refusing to crop it.')
    geometry = {'size_mm': size_mm, 'measure': measure,
                'across_flats_mm': 2 * outer_a, 'across_vertices_mm': 2 * outer_a / COS30,
                'border_mm': border_mm, 'clearance_mm': clearance_mm,
                'canvas_width_mm': float(width), 'canvas_height_mm': float(height),
                'outer_apothem_mm': outer_a, 'inner_apothem_mm': inner_a,
                'outer_vertices_mm': (outer + origin).tolist(),
                'model_hull_mm': (model_hull_mm + origin).tolist(),
                'center_mm': origin.tolist(), 'scale_mm_per_source_unit': scale,
                'curve_error_bound_mm': tolerance * scale,
                'max_model_support_with_error_mm': max_support,
                'containment_verified': True}
    return root, geometry


def card_layout(width, height, padding, margin, orientation, copies=None):
    page_w, page_h = (210., 297.) if orientation == 'portrait' else (297., 210.)
    side = max(width, height) + 2 * padding
    cols = math.floor((page_w - 2 * margin + 1e-9) / side)
    rows = math.floor((page_h - 2 * margin + 1e-9) / side)
    capacity = cols * rows
    if cols < 1 or rows < 1:
        raise ValueError(f'Square card {side:.2f} mm does not fit A4 with '
                         f'{margin:g} mm margins. Size was not reduced.')
    count = capacity if copies is None else copies
    if count < 1 or count > capacity:
        raise ValueError(f'--copies must be between 1 and {capacity} for this sheet.')
    used_cols = min(cols, count)
    used_rows = math.ceil(count / cols)
    x0 = (page_w - used_cols * side) / 2
    y0 = (page_h - used_rows * side) / 2
    cards = []
    for i in range(count):
        row, col = divmod(i, cols)
        x, y = x0 + col * side, y0 + row * side
        cards.append({'x_mm': x, 'y_mm': y, 'side_mm': side,
                      'tile_x_mm': x + (side - width) / 2,
                      'tile_y_mm': y + (side - height) / 2})
    return {'page_width_mm': page_w, 'page_height_mm': page_h,
            'orientation': orientation, 'margin_mm': margin, 'padding_mm': padding,
            'card_side_mm': side, 'columns': used_cols, 'rows': used_rows,
            'capacity': capacity, 'copies': count, 'grid_x_mm': x0, 'grid_y_mm': y0,
            'coordinate_origin': 'top-left', 'cards': cards}


def write_pdf(svg_file, destination, work, layout, guides, renderer):
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter
    renderer.svg2pdf(url=str(svg_file), write_to=str(work / 'single-vector.pdf'))
    page_w, page_h = layout['page_width_mm'], layout['page_height_mm']
    blank = work / 'card-grid.pdf'
    c = canvas.Canvas(str(blank), pagesize=(page_w * MM_PT, page_h * MM_PT))
    c.setTitle('TiGames - A4 square cards - print at 100 percent')
    if guides:
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.08 * MM_PT)
        c.setDash(1.5 * MM_PT, 1.5 * MM_PT)
        x0, y0, side = layout['grid_x_mm'], layout['grid_y_mm'], layout['card_side_mm']
        for col in range(layout['columns'] + 1):
            x = (x0 + col * side) * MM_PT
            c.line(x, (page_h - y0) * MM_PT,
                   x, (page_h - y0 - layout['rows'] * side) * MM_PT)
        for row in range(layout['rows'] + 1):
            y = (page_h - y0 - row * side) * MM_PT
            c.line(x0 * MM_PT, y, (x0 + layout['columns'] * side) * MM_PT, y)
    c.showPage()
    c.save()
    writer = PdfWriter()
    writer.add_page(PdfReader(blank).pages[0])
    page = writer.pages[0]
    tile = PdfReader(work / 'single-vector.pdf').pages[0]
    height = float(tile.mediabox.height) / MM_PT
    for card in layout['cards']:
        page.merge_translated_page(tile, card['tile_x_mm'] * MM_PT,
                                   (page_h - card['tile_y_mm'] - height) * MM_PT)
    writer.pages[0].compress_content_streams()
    writer.add_metadata({'/Title': 'TiGames - A4 square cards - print at 100 percent'})
    with destination.open('wb') as stream:
        writer.write(stream)
    check = PdfReader(destination)
    assert len(check.pages) == 1
    for page in check.pages:
        assert not list(page.images), 'Unexpected raster in PDF'
        assert abs(float(page.mediabox.width) / MM_PT - page_w) < 0.001
        assert abs(float(page.mediabox.height) / MM_PT - page_h) < 0.001


def save_png_and_checks(svg, output_dir, geometry, dpi, renderer):
    width = math.ceil(geometry['canvas_width_mm'] / 25.4 * dpi)
    height = math.ceil(geometry['canvas_height_mm'] / 25.4 * dpi)
    if width * height > 80_000_000:
        raise ValueError('Output PNG exceeds 80 megapixels; reduce --png-dpi.')
    raw = output_dir / 'work' / 'rendered-alpha.png'
    renderer.svg2png(url=str(svg), write_to=str(raw), output_width=width, output_height=height)
    rgba = np.asarray(Image.open(raw).convert('RGBA'))
    assert not np.any(rgba[rgba[:, :, 3] > 0, :3]), 'SVG contains nonblack visible pixels'
    binary = np.zeros_like(rgba)
    binary[:, :, 3] = (rgba[:, :, 3] >= 128).astype('uint8') * 255
    Image.fromarray(binary).save(output_dir / 'model-outline.png', dpi=(dpi, dpi), optimize=True)
    # Check images are explicitly not the transparent deliverable.
    for name, color in [('check-blue.png', (150, 215, 230, 255)),
                        ('check-dark.png', (65, 65, 65, 255))]:
        bg = Image.new('RGBA', (width, height), color)
        bg.alpha_composite(Image.fromarray(binary))
        bg.convert('RGB').save(output_dir / name)
    return [width, height]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lineart', type=Path, required=True,
                   help='Approved/generated contour PNG; NOT a raw photo')
    p.add_argument('--size-mm', type=float, required=True,
                   help='Outer frame size including its border, in millimeters')
    p.add_argument('--measure', choices=['across-flats', 'across-vertices'], required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--border-mm', type=float, default=0.12)
    p.add_argument('--clearance-mm', type=float, default=0.03)
    p.add_argument('--cell-padding-mm', type=float, default=3.)
    p.add_argument('--page-margin-mm', type=float, default=10.)
    p.add_argument('--page-orientation', choices=['portrait', 'landscape'], default='portrait')
    p.add_argument('--copies', type=int, help='Count on one A4 sheet; default fills square grid')
    p.add_argument('--no-cut-guides', action='store_true')
    p.add_argument('--png-dpi', type=int, default=600)
    p.add_argument('--ink-threshold', type=float, default=0.45)
    p.add_argument('--angle-step-deg', type=float, default=0.5)
    p.add_argument('--curve-tolerance', type=float, default=0.08,
                   help='Maximum Bezier flattening error in source vector units')
    p.add_argument('--overwrite', action='store_true')
    return p.parse_args(argv)


def build(args):
    for name in ['size_mm', 'border_mm', 'curve_tolerance', 'angle_step_deg']:
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            raise ValueError(f'{name} must be finite and positive.')
    for name in ['clearance_mm', 'cell_padding_mm', 'page_margin_mm']:
        if not math.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            raise ValueError(f'{name} must be finite and nonnegative.')
    if not 0 < args.ink_threshold <= 1:
        raise ValueError('--ink-threshold must be between 0 (exclusive) and 1.')
    if not 0 < args.angle_step_deg <= 10:
        raise ValueError('--angle-step-deg must be at most 10 degrees.')
    if not 72 <= args.png_dpi <= 4800:
        raise ValueError('--png-dpi must be between 72 and 4800.')
    out = args.output_dir
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise ValueError('Output directory is not empty; choose a new one or explicitly --overwrite.')
    if not args.lineart.is_file():
        raise ValueError(f'Contour image not found: {args.lineart}')
    renderer = cairo_renderer()
    work = out / 'work'
    work.mkdir(parents=True, exist_ok=True)
    ink = prepare_png(args.lineart, work / 'prepared-lineart.png', args.ink_threshold)
    trace_input = work / 'trace-input.png'
    Image.fromarray(np.where(ink, 0, 255).astype('uint8')).save(trace_input)
    traced_file = work / 'traced-model.svg'
    vtracer.convert_image_to_svg_py(str(trace_input), str(traced_file), colormode='binary',
        mode='spline', filter_speckle=0, corner_threshold=60, length_threshold=3.5,
        max_iterations=10, splice_threshold=45, path_precision=3)
    traced = ET.parse(traced_file).getroot()
    points, hull = vector_geometry(traced, args.curve_tolerance)
    fit = fit_regular_hexagon(hull, args.angle_step_deg)
    root, geometry = build_svg(traced, hull, fit, args.size_mm, args.measure,
                              args.border_mm, args.clearance_mm, args.curve_tolerance)
    layout = card_layout(geometry['canvas_width_mm'], geometry['canvas_height_mm'],
                         args.cell_padding_mm, args.page_margin_mm,
                         args.page_orientation, args.copies)
    svg = out / 'model-outline.svg'
    ET.ElementTree(root).write(svg, encoding='utf-8', xml_declaration=True)
    if any(el.tag.endswith('image') or el.tag.endswith('clipPath') for el in root.iter()):
        raise RuntimeError('Raster or clipping element found in final SVG.')
    pixels = save_png_and_checks(svg, out, geometry, args.png_dpi, renderer)
    write_pdf(svg, out / 'sheet-a4.pdf', work, layout, not args.no_cut_guides, renderer)
    manifest = {
        'schema_version': 1,
        'source': {'file': os.path.relpath(args.lineart.resolve(), out.resolve()),
                   'sha256': hashlib.sha256(args.lineart.read_bytes()).hexdigest()},
        'geometry': geometry,
        'fit': {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in fit.items()},
        'layout': layout,
        'raster': {'dpi': args.png_dpi, 'pixel_size': pixels, 'rgb': [0, 0, 0],
                   'alpha_values': [0, 255], 'ink_threshold': args.ink_threshold},
        'checks': {'model_contained_with_curve_error_bound': True,
                   'svg_embedded_rasters': 0, 'pdf_embedded_rasters': 0,
                   'svg_visible_colors': ['#000000'], 'pdf_page_size_verified': True},
        'print': {'paper': 'A4', 'scale_percent': 100, 'fit_to_page': False,
                   'cut_guides': not args.no_cut_guides},
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def main(argv=None):
    args = parse_args(argv)
    try:
        manifest = build(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    g, layout = manifest['geometry'], manifest['layout']
    print(f"Created {args.output_dir}: {g['size_mm']:g} mm {g['measure']}; "
          f"square cards {layout['card_side_mm']:.2f} mm; "
          f"{layout['copies']} cards on A4. Print at 100%.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
