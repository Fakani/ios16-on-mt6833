#!/usr/bin/env python3
"""Test strict FwUp/HEX parsing, CRCs and non-overlapping IRAM mappings."""
from pathlib import Path
import struct
import unittest
from parse_ilitek_firmware import crc32_mpeg2, parse_firmware, unwrap


def record(kind, data=b'', address=0):
    body=bytes([len(data)])+address.to_bytes(2,'big')+bytes([kind])+data
    return ':'+(body+bytes([-sum(body)&255])).hex().upper()


def sample(*, corrupt_block=False, fixed=True, bad_target=False, conflict=False):
    lines=[]
    blocks=[(1,0,b'AP-CODE-TEST!'),(2,0x20,b'DATA-CODE---'),(3,0x40,b'TUNE'),(5,0x60,b'MP--')]
    for ident,start,data in blocks:
        end=start+len(data)+3
        lines.append(record(0xaf,start.to_bytes(3,'big')+end.to_bytes(3,'big')+bytes([ident])))
    if fixed:
        lines.append(record(0xb0,(0x20870).to_bytes(3,'big')+b'\x02'))
        lines.append(record(0xb0,(0x20670).to_bytes(3,'big')+b'\x03'))
    if bad_target:lines.append(record(0xb0,(0x4009c).to_bytes(3,'big')+b'\x01'))
    for ident,start,data in blocks:
        block=data+crc32_mpeg2(data).to_bytes(4,'big')
        if corrupt_block and ident==1:block=bytes([block[0]^1])+block[1:]
        lines.append(record(0,block,start))
    if conflict:lines.append(record(0,b'\0',0))
    lines.extend([record(3,b'\0\0\x04\xb8'),record(1)])
    return ('\r\n'.join(lines)+'\r\n').encode()


def wrap(payload):
    header=bytearray(80);header[:4]=b'FwUp'
    struct.pack_into('<4I',header,4,1,0,len(payload),0x80000000)
    header[20:27]=b'test.img'[:7]
    return bytes(header)+payload+bytes(128)


class FirmwareTests(unittest.TestCase):
    def test_crc_mpeg2_reference_vector(self):
        self.assertEqual(crc32_mpeg2(b'123456789'),0x0376e6e7)
        self.assertEqual(crc32_mpeg2(b''),0xffffffff)

    def test_af_b0_and_wrapper(self):
        image,manifest=parse_firmware(wrap(sample()))
        blocks={b['id']:b for b in manifest['blocks']}
        self.assertEqual(blocks[1]['target_start'],0)
        self.assertEqual(blocks[2]['target_start'],0x20870)
        self.assertEqual(blocks[3]['target_start'],0x20670)
        self.assertFalse(blocks[5]['active_application'])
        self.assertFalse(manifest['wrapper']['signature_verified'])
        self.assertEqual(manifest['entry_address'],0x4b8)
        self.assertEqual(image[:len(b'AP-CODE-TEST!')],b'AP-CODE-TEST!')

    def test_default_data_and_tuning_mapping(self):
        _,manifest=parse_firmware(sample(fixed=False))
        blocks={b['id']:b for b in manifest['blocks']}
        self.assertEqual(blocks[2]['target_start'],0x20610)
        self.assertEqual(blocks[3]['target_start'],0x20610+blocks[2]['length'])

    def test_record_and_block_corruption_fail(self):
        data=bytearray(sample());data[9]^=1
        with self.assertRaises(ValueError):parse_firmware(bytes(data))
        with self.assertRaises(ValueError):parse_firmware(sample(corrupt_block=True))

    def test_address_and_overlap_guards(self):
        with self.assertRaises(ValueError):parse_firmware(sample(bad_target=True))
        with self.assertRaises(ValueError):parse_firmware(sample(conflict=True))

    def test_wrapper_length_and_unknown_format_fail(self):
        with self.assertRaises(ValueError):unwrap(wrap(sample())[:-1])
        with self.assertRaises(ValueError):unwrap(b'UNKNOWN')

    def test_eof_and_metadata_order_guards(self):
        with self.assertRaises(ValueError):parse_firmware(sample()+record(0,b'X').encode())
        with self.assertRaises(ValueError):parse_firmware((record(0xb0,b'\0\0\0\x01')+'\n').encode()+sample())

    @unittest.skipUnless((Path(__file__).resolve().parents[2]/'assets/device/touch/FW_NF_ILI7807S_TIANMA.img').exists(),'local device firmware excluded from repo')
    def test_exact_device_firmware(self):
        path=Path(__file__).resolve().parents[2]/'assets/device/touch/FW_NF_ILI7807S_TIANMA.img'
        image,m=parse_firmware(path.read_bytes())
        self.assertEqual(m['raw_sha256'],'d6a38c0382ec3f570d6cb282e11ec4ee075000482f3b653334770851518f0e77')
        self.assertEqual(len(image),127488)
        self.assertEqual(m['application_bytes'],90624)
        blocks={b['name']:b for b in m['blocks']}
        self.assertEqual(blocks['AP']['crc32'],'0xbb7b8d39')
        self.assertEqual(blocks['DATA']['crc32'],'0x061ef7ef')
        self.assertEqual(blocks['TUNING']['crc32'],'0x7532981c')
        self.assertEqual(blocks['MP']['crc32'],'0xb4536eea')


if __name__=='__main__':unittest.main(verbosity=2)
