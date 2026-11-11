#!/usr/bin/env python3
"""Patch only the old XNU touch-thread window in the tested v78 image.

Offline candidate: preserve verified firmware loading; enable touchscreen=3.
The replacement never resets GPIO15 or downloads firmware again.
"""
import argparse
import gzip
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from make_touch_ack2_image import parse_image,require,sha256,LOADER_LIMIT
from make_touch_gate_images import repack

BASE_SHA='66a413df7488859ca828134ace5e32e6e2f2db604d5d66b88230535e7e1ffad2'
MACHO_OFFSET=0x31eb020
THREAD=0xfffffff0074e2afc
WINDOW=0x12a8
SYMBOLS={'_touch_thread':THREAD,'_spi_msg':THREAD+WINDOW,
 '_printf':0xfffffff0072f5b90,'_delay':0xfffffff0072cbc08,
 '_ml_io_map':0xfffffff007447dbc,'_hakios_touch_post':0xfffffff0074a4c20,
 '_clock_interval_to_absolutetime_interval':0xfffffff00744d4a8,
 '_mach_absolute_time':0xfffffff00744cfbc,'_ml_delay_should_spin':0xfffffff0074492cc,
 '_get_preemption_level':0xfffffff00743e2a0,'_ml_get_interrupts_enabled':0xfffffff007446ca8}
HERE=Path(__file__).resolve().parent


def locate_thread(blob):
    mo=MACHO_OFFSET
    require(struct.unpack_from('<I',blob,mo)[0]==0xfeedfacf,'Mach-O magic mismatch')
    ncmds,command_bytes=struct.unpack_from('<II',blob,mo+16)
    require(ncmds<256 and command_bytes<0x10000,'invalid Mach-O command table')
    segments=[];symtab=None;at=mo+32
    for _ in range(ncmds):
        cmd,size=struct.unpack_from('<II',blob,at)
        require(size>=8 and at+size<=mo+32+command_bytes,'invalid load command')
        if cmd==0x19:
            name=blob[at+8:at+24].split(b'\0')[0].decode()
            vm,vs,fo,fs=struct.unpack_from('<4Q',blob,at+24)
            prot=struct.unpack_from('<I',blob,at+60)[0]
            segments.append((name,vm,fo,fs,prot))
        if cmd==2:symtab=struct.unpack_from('<4I',blob,at+8)
        at+=size
    require(symtab is not None,'symbol table missing')
    offset,count,strings,size=symtab;table=blob[mo+strings:mo+strings+size];found={}
    for i in range(count):
        ni,kind,section,desc,value=struct.unpack_from('<IBBHQ',blob,mo+offset+i*16)
        if ni>=len(table):continue
        end=table.find(b'\0',ni)
        if end<0:continue
        name=table[ni:end].decode(errors='replace')
        if name in SYMBOLS:
            require(name not in found or found[name]==value,'ambiguous kernel symbol')
            found[name]=value
    require(found==SYMBOLS,'kernel symbol addresses differ from audited baseline')
    for name,vm,fo,fs,prot in segments:
        if vm<=THREAD and THREAD+WINDOW<=vm+fs:
            require(prot&4,'thread window is not executable')
            position=mo+fo+THREAD-vm
            require(position==0x36c9b1c,'kernel file mapping mismatch')
            require(blob[position:position+16]==bytes.fromhex('ffc303d1fc6f09a9fa670aa9f85f0ba9'),'old thread bytes mismatch')
            return position
    raise ValueError('thread not inside one file-backed segment')


def compile_thread(tmp,counter_wait=0,timing_log=0):
    require(not counter_wait or timing_log,'counter wait requires calibration/profile')
    obj,ld,elf,binary=[tmp/x for x in ('thread.o','link.ld','thread.elf','thread.bin')]
    command=['clang','--target=aarch64-linux-gnu','-ffreestanding','-nostdlib','-fno-builtin',
             '-mgeneral-regs-only','-mstrict-align','-fno-stack-protector','-fno-omit-frame-pointer',
             '-DTOUCH_COUNTER_WAIT='+str(counter_wait),'-DTOUCH_TIMING_LOG='+str(timing_log),
             '-Oz','-Wall','-Wextra','-Werror','-c',str(HERE.parent/'include/touch-kernel-thread.c'),'-o',str(obj)]
    subprocess.run(command,check=True,capture_output=True)
    ld.write_text('''ENTRY(touch_thread_entry)
SECTIONS {
 . = 0xfffffff0074e2afc;
 .text : { *(.text.entry) *(.text .text.*) }
 .rodata : { *(.rodata*) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
''')
    definitions=['--defsym=kernel_map='+hex(SYMBOLS['_ml_io_map']),
                 '--defsym=kernel_delay='+hex(SYMBOLS['_delay']),
                 '--defsym=kernel_printf='+hex(SYMBOLS['_printf']),
                 '--defsym=kernel_post='+hex(SYMBOLS['_hakios_touch_post']),
                 '--defsym=kernel_time='+hex(SYMBOLS['_mach_absolute_time']),
                 '--defsym=kernel_interval='+hex(SYMBOLS['_clock_interval_to_absolutetime_interval']),
                 '--defsym=kernel_spin_decision='+hex(SYMBOLS['_ml_delay_should_spin']),
                 '--defsym=kernel_preempt_level='+hex(SYMBOLS['_get_preemption_level']),
                 '--defsym=kernel_irq_enabled='+hex(SYMBOLS['_ml_get_interrupts_enabled'])]
    base=['ld.lld','-T',str(ld)]+definitions+[str(obj)]
    subprocess.run(base+['-o',str(elf)],check=True,capture_output=True)
    subprocess.run(base+['--oformat=binary','-o',str(binary)],check=True,capture_output=True)
    data=elf.read_bytes();require(struct.unpack_from('<Q',data,24)[0]==THREAD,'thread entry moved')
    shoff=struct.unpack_from('<Q',data,40)[0];entsize,num=struct.unpack_from('<HH',data,58)
    for n in range(num):
        section=struct.unpack_from('<IIQQQQIIQQ',data,shoff+n*entsize)
        if section[2]&2 and section[5]:
            require(not section[2]&1,'kernel replacement contains writable static state')
            require(THREAD<=section[3] and section[3]+section[5]<=THREAD+WINDOW,'thread section exceeds window')
    code=binary.read_bytes();require(len(code)<=WINDOW,'replacement exceeds old thread')
    return code


def build_hid_image(baseline,counter_wait=0,timing_log=0):
    require(sha256(baseline)==BASE_SHA,'input must be tested v78-FW-BIG image')
    _,parts,_,_=parse_image(baseline);blob=bytearray(gzip.decompress(parts[0]));old=bytes(blob)
    position=locate_thread(blob)
    with tempfile.TemporaryDirectory() as tmp:code=compile_thread(Path(tmp),counter_wait,timing_log)
    padded=code+bytes((-len(code))%4)
    require(len(padded)<=WINDOW,'aligned code too large')
    blob[position:position+WINDOW]=padded+bytes.fromhex('1f2003d5')*((WINDOW-len(padded))//4)
    before=b'touchscreen=0 loader_return_after=300';after=b'touchscreen=3 loader_return_after=300'
    require(old[:LOADER_LIMIT].count(before)==2,'expected exactly two bootarg strings')
    prefix=bytes(blob[:LOADER_LIMIT]).replace(before,after)
    blob[:LOADER_LIMIT]=prefix
    require(bytes(blob[0x20000:LOADER_LIMIT])==old[0x20000:LOADER_LIMIT],'verified loader/firmware data changed')
    result=repack(baseline,bytes(blob),[(position,position+WINDOW)])
    changed=[i for i,(a,b) in enumerate(zip(old[:LOADER_LIMIT],blob[:LOADER_LIMIT]))if a!=b]
    require(len(changed)==2,'unexpected loader changes')
    manifest={'output_sha256':sha256(result),'input_sha256':BASE_SHA,'image_bytes':len(result),
              'kernel_thread_va':hex(THREAD),'kernel_blob_offset':hex(position),'old_window_bytes':WINDOW,
              'replacement_bytes':len(code),'loader_changed_offsets':changed,'touchscreen':3,
              'verified_firmware_loader_preserved':True,'reset_gpio15_in_new_thread':False,
              'new_thread_host_download':False,'packet_id':'0x5b','packet_bytes':72,
              'checksum':'sum(all 72 bytes) modulo 256 == 0','coordinate_limits':[4320,9600],
              'counter_wait':bool(counter_wait),'timing_log':bool(timing_log),
              'nominal_half_period_us':10,'idle_delay_us':1000,
              'hardware_result':'NOT TESTED'}
    return result,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--counter-wait',action='store_true');p.add_argument('--timing-log',action='store_true')
    a=p.parse_args();manifest_path=a.output.with_suffix('.manifest.json')
    require(not a.output.exists() and not manifest_path.exists(),'output exists')
    result,manifest=build_hid_image(a.baseline.read_bytes(),int(a.counter_wait),int(a.timing_log));a.output.write_bytes(result)
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
