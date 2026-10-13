"""Purely local CLI behavior checks using generated images only."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from pypdf import PdfReader


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'invoice_artifacts.py'


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.source = self.dir / 'input.png'
        image = Image.new('RGB', (100, 80), 'white')
        for point, color in [((0, 0), (220, 20, 20)), ((1, 0), (20, 20, 220)), ((2, 0), (10, 10, 10))]:
            image.putpixel(point, color)
        image.save(self.source)
        self.original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.original_hash)
        self.temp.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr or result.stdout)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_captcha_keeps_original_and_selected_pixels(self):
        for color, position in [('red', (0, 0)), ('blue', (1, 0)), ('black', (2, 0))]:
            output = self.run_cli('captcha', '--input', self.source, '--color', color, '--output-dir', self.dir / color, '--scale', 2)
            self.assertEqual(Path(output['source']).read_bytes(), self.source.read_bytes())
            with Image.open(output['enlarged']) as enlarged, Image.open(output['filtered']) as filtered, Image.open(self.source) as source:
                self.assertEqual(enlarged.size, (200, 160))
                self.assertEqual(filtered.getpixel((position[0] * 2, 0)), source.getpixel(position))
                other = 1 if color == 'red' else 0
                self.assertEqual(filtered.getpixel((other * 2, 0)), (255, 255, 255))
            self.assertEqual(output['retained_pixels'], 1)
        output = self.run_cli('captcha', '--input', self.source, '--color', 'all', '--output-dir', self.dir / 'all')
        with Image.open(output['enlarged']) as enlarged, Image.open(output['filtered']) as filtered:
            self.assertEqual(enlarged.tobytes(), filtered.tobytes())
        previous = Path(output['source']).read_bytes()
        repeated = self.run_cli('captcha', '--input', self.source, '--color', 'all', '--output-dir', self.dir / 'all')
        self.assertEqual(Path(repeated['source']).name, 'source-2.png')
        self.assertEqual(Path(output['source']).read_bytes(), previous)

    def test_empty_filter_reports_no_usable_pixels(self):
        white = self.dir / 'white.png'
        Image.new('RGB', (10, 10), 'white').save(white)
        output = self.run_cli('captcha', '--input', white, '--color', 'red', '--output-dir', self.dir / 'white-output')
        self.assertEqual(output['retained_pixels'], 0)
        self.assertTrue(output['no_usable_pixels'])
        self.assertTrue(output['warning'])

    def test_result_is_one_a4_page_and_does_not_overwrite(self):
        target = self.dir / 'result.pdf'
        first = self.run_cli('result', '--input', self.source, '--pdf', target, '--crop', '5,5,90,70', '--title', '官方查验结果', '--verified-at', '2000-01-01 12:00:00')
        first_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        reader = PdfReader(first['pdf'])
        self.assertEqual(len(reader.pages), 1)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 841.8898, places=3)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 595.2756, places=3)
        self.assertIn('页面截图版', reader.metadata.subject)
        with Image.open(first['png']) as saved:
            self.assertEqual(saved.size, (90, 70))
        second = self.run_cli('result', '--input', self.source, '--pdf', target)
        self.assertEqual(Path(second['pdf']).name, 'result-2.pdf')
        self.assertEqual(Path(second['png']).name, 'result-2.png')
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), first_hash)
        occupied = self.dir / 'occupied.png'
        occupied.write_bytes(b'keep me')
        third = self.run_cli('result', '--input', self.source, '--pdf', self.dir / 'occupied.pdf')
        self.assertEqual(Path(third['pdf']).name, 'occupied-2.pdf')
        self.assertEqual(occupied.read_bytes(), b'keep me')

    def test_all_color_reports_pure_colored_pixels(self):
        image = self.dir / 'pure-red.png'
        Image.new('RGB', (5, 5), (255, 0, 0)).save(image)
        output = self.run_cli('captcha', '--input', image, '--color', 'all', '--output-dir', self.dir / 'pure')
        self.assertFalse(output['no_usable_pixels'])

    def test_result_accepts_actual_jpeg_screenshot_with_png_filename(self):
        source = self.dir / 'browser.png'
        Image.new('RGB', (20, 30), 'white').save(source, format='JPEG')
        original = source.read_bytes()
        output = self.run_cli('result', '--input', source, '--pdf', self.dir / 'browser.pdf')
        with Image.open(output['png']) as exported:
            self.assertEqual(exported.format, 'PNG')
        self.assertEqual(source.read_bytes(), original)

    def test_captcha_accepts_jpeg_and_preserves_its_format_and_bytes(self):
        source = self.dir / 'captcha-browser.png'
        Image.new('RGB', (20, 10), (220, 20, 20)).save(source, format='JPEG')
        original = source.read_bytes()
        output = self.run_cli('captcha', '--input', source, '--color', 'red', '--output-dir', self.dir / 'jpeg-captcha')
        self.assertEqual(Path(output['source']).name, 'source.jpg')
        self.assertEqual(Path(output['source']).read_bytes(), original)
        for name in ['enlarged', 'filtered']:
            with Image.open(output[name]) as exported:
                self.assertEqual(exported.format, 'PNG')

    def test_invalid_options_fail_as_json(self):
        for option in ['0,0,0,5', '-1,0,5,5', '0,0,101,80', 'bad']:
            output = self.run_cli('result', '--input', self.source, '--pdf', self.dir / 'invalid.pdf', f'--crop={option}', success=False)
            self.assertIn('error', output)
            self.assertFalse((self.dir / 'invalid.pdf').exists())
        output = self.run_cli('captcha', '--input', self.source, '--color', 'red', '--output-dir', self.dir / 'bad', '--scale', 0, success=False)
        self.assertIn('error', output)


if __name__ == '__main__':
    unittest.main()
