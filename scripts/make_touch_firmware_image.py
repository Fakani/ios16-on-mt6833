#!/usr/bin/env python3
"""Build a PID/dummy-gated IRAM experiment for this exact device firmware.

Firmware data stays in the local boot-image loader padding, not in Git.
No device operations. Android/XNU payload bytes remain unchanged.
"""
import argparse
import gzip
import json
from pathlib import Path
import struct
import tempfile

from parse_ilitek_firmware import parse_firmware
from make_touch_ack2_image import BASE_SHA256,LOADER_LIMIT,build_image,parse_image,require,sha256
from make_touch_gate_images import BASE,INJECTION,INJECTION_LIMIT,CALL,CAPTURE,branch,compile_diagnostic,repack

FIRMWARE_SHA256='d6a38c0382ec3f570d6cb282e11ec4ee075000482f3b653334770851518f0e77'
DATA_OFFSET=0x24000
PACKAGE_OFFSET=0x3f000
EXPECTED=((1,0,81920,0xbb7b8d39),(2,0x20870,8192,0x061ef7ef),(3,0x20670,512,0x7532981c))


def firmware_package(raw):
    require(sha256(raw)==FIRMWARE_SHA256,'input is not the audited device firmware')
    image,manifest=parse_firmware(raw)
    by_id={b['id']:b for b in manifest['blocks']}
    data,descriptors=bytearray(),[]
    for ident,target,size,crc in EXPECTED:
        b=by_id[ident]
        require(b['active_application'] and b['target_start']==target and b['length']==size and
                int(b['crc32'],16)==crc,'device block mapping differs')
        chunk=image[b['source_start']:b['source_end']+1]
        descriptors.append((target,size,len(data),crc))
        data.extend(chunk)
    require(len(data)==90624,'application byte count differs')
    package=struct.pack('<8I',0x57464c49,1,3,len(data),0x78071f05,60000,0,0)
    package+=b''.join(struct.pack('<4I',*d)for d in descriptors)
    require(len(package)==80,'package layout mismatch')
    return bytes(data),package,manifest


def build_firmware_image(baseline,firmware):
    require(sha256(baseline)==BASE_SHA256,'baseline SHA256 mismatch')
    fw_data,package,fw_manifest=firmware_package(firmware)
    ack2,_=build_image(baseline)
    _,parts,_,_=parse_image(ack2)
    blob=bytearray(gzip.decompress(parts[0]))
    original=bytes(blob)
    require(blob[CALL:CALL+4]==bytes.fromhex('fb060094'),'probe caller mismatch')
    require(blob[CAPTURE:CAPTURE+4]==bytes.fromhex('93c25fb8'),'FIFO hook mismatch')
    require(struct.unpack_from('<QQ',blob,0xf88)==(0x4008c000,0x400904d8),'BSS boundary mismatch')
    require(not any(blob[INJECTION:LOADER_LIMIT]),'loader padding is not empty')
    require(INJECTION_LIMIT<=DATA_OFFSET and DATA_OFFSET+len(fw_data)<=PACKAGE_OFFSET and
            PACKAGE_OFFSET+len(package)<=LOADER_LIMIT,'firmware regions overlap')
    with tempfile.TemporaryDirectory() as tmp:
        code,entry,hook=compile_diagnostic(0,Path(tmp),big_font=1,gpio_probe=1,gpio_rw_test=1,firmware_load=1)
    blob[INJECTION:INJECTION+len(code)]=code
    blob[DATA_OFFSET:DATA_OFFSET+len(fw_data)]=fw_data
    blob[PACKAGE_OFFSET:PACKAGE_OFFSET+len(package)]=package
    blob[CALL:CALL+4]=branch(BASE+CALL,entry,link=True)
    blob[CAPTURE:CAPTURE+4]=branch(BASE+CAPTURE,hook)
    require(blob[LOADER_LIMIT:]==original[LOADER_LIMIT:],'payload changed')
    result=repack(baseline,bytes(blob))
    manifest={'output_sha256':sha256(result),'image_bytes':len(result),
              'baseline_sha256':BASE_SHA256,'device_firmware_sha256':FIRMWARE_SHA256,
              'code_offset':hex(INJECTION),'code_bytes':len(code),'entry':hex(entry),'capture':hex(hook),
              'application_data_offset':hex(DATA_OFFSET),'application_data_bytes':len(fw_data),
              'package_offset':hex(PACKAGE_OFFSET),'package_bytes':len(package),
              'blocks':[dict(zip(('target','size','offset','crc32'),d))for d in
                        (struct.unpack_from('<4I',package,32+i*16)for i in range(3))],
              'global_deadline_ms':60000,'verification':'full byte readback plus independent software CRC',
              'dma_crc_used':False,'flash_writes':False,'touchscreen':0,
              'android_xnu_tail_identical':True,'hardware_result':'NOT TESTED'}
    return result,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('firmware',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();manifest_path=a.output.with_suffix('.manifest.json')
    require(not a.output.exists() and not manifest_path.exists(),'output exists')
    result,manifest=build_firmware_image(a.baseline.read_bytes(),a.firmware.read_bytes())
    a.output.write_bytes(result);manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
