"""Observable geometry, transparency, sizing and print-layout checks."""
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('factory', ROOT / '.agents/skills/photo-to-hexagon/scripts/build.py')
factory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(factory)


class FactoryTests(unittest.TestCase):
    def test_fits_known_rotated_hexagon_and_finds_its_center(self):
        # Independent fixture: exact regular hexagon, rotated and translated.
        radius = 117.
        vertex_angle = math.radians(41.37)
        angles = vertex_angle + np.arange(6) * math.pi / 3
        center = np.array([400., -200.])
        polygon = center + radius * np.column_stack([np.cos(angles), np.sin(angles)])
        answer = factory.fit_regular_hexagon(polygon)
        self.assertAlmostEqual(answer['apothem'], radius * math.sqrt(3) / 2, places=4)
        np.testing.assert_allclose(answer['center'], center, atol=1e-4)

    def test_opaque_white_hole_removed_and_yellow_thin_line_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source.png', Path(tmp) / 'target.png'
            im = Image.new('RGBA', (80, 80), (0, 0, 0, 0))
            draw = ImageDraw.Draw(im)
            draw.ellipse((10, 10, 60, 60), fill='white', outline='black', width=3)
            draw.line((65, 10, 65, 70), fill=(255, 210, 0, 255), width=1)
            im.save(source)
            factory.prepare_png(source, target, .45)
            result = np.asarray(Image.open(target))
            self.assertEqual(result[35, 35, 3], 0)
            self.assertEqual(result[35, 65, 3], 255)
            self.assertEqual(set(np.unique(result[:, :, 3])), {0, 255})
            self.assertTrue(np.all(result[:, :, :3] == 0))

    def test_square_grid_with_padding_and_page_margins(self):
        layout = factory.card_layout(37, 33, 3, 10, 'portrait')
        self.assertEqual(layout['card_side_mm'], 43)
        self.assertEqual(layout['copies'], 24)
        for card in layout['cards']:
            self.assertGreaterEqual(card['x_mm'], 10)
            self.assertGreaterEqual(card['y_mm'], 10)
            self.assertLessEqual(card['x_mm'] + card['side_mm'], 200)
            self.assertLessEqual(card['y_mm'] + card['side_mm'], 287)
            self.assertGreaterEqual(card['tile_x_mm'] - card['x_mm'], 3)
            self.assertGreaterEqual(card['tile_y_mm'] - card['y_mm'], 3)

    def test_oversized_card_and_excess_copies_are_not_silently_shrunk(self):
        with self.assertRaises(ValueError):
            factory.card_layout(220, 180, 3, 10, 'portrait')
        with self.assertRaises(ValueError):
            factory.card_layout(37, 33, 3, 10, 'portrait', 25)

    def test_build_both_physical_measurements_and_real_vector_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / 'lineart.png'
            im = Image.new('RGBA', (300, 180), (0, 0, 0, 0))
            draw = ImageDraw.Draw(im)
            draw.ellipse((40, 30, 140, 130), fill='white', outline='black', width=4)
            draw.rectangle((170, 50, 270, 110), fill='white', outline=(255, 210, 0, 255), width=3)
            draw.line((145, 80, 165, 80), fill='black', width=1)
            im.save(source)
            for measure in ['across-flats', 'across-vertices']:
                output = tmp / measure
                args = factory.parse_args(['--lineart', str(source), '--size-mm', '34',
                    '--measure', measure, '--output-dir', str(output), '--copies', '2',
                    '--png-dpi', '300'])
                manifest = factory.build(args)
                root = ET.parse(output / 'model-outline.svg').getroot()
                polygon = root.find('.//{' + factory.NS + '}polygon')
                verts = np.array([list(map(float, p.split(',')))
                                  for p in polygon.get('points').split()])
                # Derive outer dimensions from actual path + miter stroke, not manifest.
                center = verts.mean(axis=0)
                vertex_radius = np.linalg.norm(verts - center, axis=1)
                np.testing.assert_allclose(vertex_radius, vertex_radius[0], atol=1e-7)
                edge_lengths = np.linalg.norm(verts - np.roll(verts, 1, axis=0), axis=1)
                np.testing.assert_allclose(edge_lengths, edge_lengths[0], atol=1e-7)
                stroke = float(polygon.get('stroke-width'))
                outer_flats = 2 * vertex_radius[0] * math.sqrt(3) / 2 + stroke
                outer_vertices = outer_flats / (math.sqrt(3) / 2)
                actual = outer_flats if measure == 'across-flats' else outer_vertices
                self.assertAlmostEqual(actual, 34, places=6)
                self.assertIsNone(root.find('.//{' + factory.NS + '}image'))
                png = Image.open(output / 'model-outline.png').convert('RGBA')
                rgba = np.asarray(png)
                self.assertEqual(set(np.unique(rgba[:, :, 3])), {0, 255})
                self.assertTrue(np.all(rgba[:, :, :3] == 0))
                # Check a formerly opaque white hole after full tracing and scaling.
                group = root.find('{' + factory.NS + '}g')
                matrix = list(map(float, group.get('transform')[7:-1].split()))
                x, y = matrix[0] * 90 + matrix[4], matrix[3] * 80 + matrix[5]
                w, h = manifest['geometry']['canvas_width_mm'], manifest['geometry']['canvas_height_mm']
                px, py = int(x / w * png.width), int(y / h * png.height)
                self.assertEqual(png.getpixel((px, py))[3], 0)
                pdf = PdfReader(output / 'sheet-a4.pdf')
                self.assertEqual(len(pdf.pages), 1)
                self.assertFalse(list(pdf.pages[0].images))
                self.assertAlmostEqual(float(pdf.pages[0].mediabox.width) / factory.MM_PT, 210, places=4)
                self.assertEqual(manifest['layout']['copies'], 2)
                self.assertTrue(manifest['checks']['model_contained_with_curve_error_bound'])


if __name__ == '__main__':
    unittest.main()
