import binascii
import importlib.util
from pathlib import Path
import struct
import tempfile
import sys
import unittest
import zlib
spec = importlib.util.spec_from_file_location('parity', Path(__file__).resolve().parents[1] / 'parity.py')
parity = importlib.util.module_from_spec(spec); spec.loader.exec_module(parity)

def image(path, pixel, color=6, gamma=None):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', binascii.crc32(kind+body))
    profile = chunk(b'gAMA', struct.pack('>I', gamma)) if gamma else b''
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',1,1,8,color,0,0,0)) + profile + chunk(b'IDAT',zlib.compress(b'\0'+bytes(pixel))) + chunk(b'IEND',b''))

class ParityTests(unittest.TestCase):
    def testAlphaDifferenceCannotBeHiddenByIdenticalRgb(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a.png'; b=Path(directory)/'b.png'
            image(a,(0,0,0,0)); image(b,(0,0,0,255))
            difference=parity.difference(a,b)
            self.assertEqual(difference['mean_alpha_error'],255)
            self.assertEqual(difference['mean_raw_rgb_error'],0)
            self.assertGreater(difference['mean_channel_error'],0)
    def testRgbAndOpaqueRgbaHaveSameAppearance(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a.png'; b=Path(directory)/'b.png'
            image(a,(80,90,100),2); image(b,(80,90,100,255))
            difference=parity.difference(a,b)
            self.assertEqual(difference['mean_alpha_error'],0)
            self.assertEqual(difference['mean_channel_error'],0)

    @unittest.skipUnless(sys.platform == 'darwin', 'native PNG comparator requires Swift on macOS')
    def test_native_and_reference_preserve_partial_alpha_transparent_rgb_and_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); left=root/'left'; right=root/'right'; left.mkdir(); right.mkdir()
            examples = [((255,1,90,1),(90,255,4,2)), ((255,0,0,0),(0,255,0,0)),
                        ((12,100,240,127),(240,10,100,128)), ((5,7,9,255),(6,8,10,255))]
            cases={}
            for index,(a,b) in enumerate(examples):
                name=str(index); cases[name]={}
                for folder,pixel in ((left,a),(right,b)):
                    for suffix in ('','-repeat'): image(folder/(name+suffix+'.png'),pixel,gamma=45455)
            measured=parity.native_differences(left,right,cases)
            for name in cases:
                self.assertEqual(measured[name]['cross_host'],parity.difference(left/(name+'.png'),right/(name+'.png')))

    def test_profile_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a.png'; b=Path(directory)/'b.png'
            image(a,(80,90,100,255),gamma=45455); image(b,(80,90,100,255),gamma=100000)
            with self.assertRaisesRegex(ValueError,'profiles differ'): parity.difference(a,b)
