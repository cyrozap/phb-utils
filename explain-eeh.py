#!/usr/bin/env python3
#
# explain-eeh.py - PHB EEH error explainer
# Copyright (C) 2019-2021, 2023  Forest Crossman <cyrozap@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#


import csv
import fileinput
import glob
import re
import struct
import textwrap
from pathlib import Path


REGISTERS = {}


def extract_bits_be(data):
    '''Extract big-endian bits (MSB is 0)'''
    bits = []
    bit_count = len(data)*8//2
    number = int(data, 16)
    for i in range(bit_count):
        bit_set = number & (1 << (bit_count - 1 - i))
        if bit_set:
            bits.append(i)

    return bits

def extract_bit_field_be(data, offset, length):
    '''Extract big-endian bits (MSB is 0)'''
    bits = 0
    bit_count = len(data)*8//2
    number = int(data, 16)
    for i in range(bit_count):
        if i not in range(offset, offset+length):
            continue
        bit_set = number & (1 << (bit_count - 1 - i))
        if bit_set:
            bits |= (1 << (offset + length - 1 - i))

    return bits

def pr_field_bits_be(fields, data):
    assert len(fields) == len(data)
    for i in range(len(data)):
        bits = extract_bits_be(data[i])
        field_defs = REGISTERS.get(fields[0])
        print("  {}: {}".format(fields[i], bits))
        if field_defs:
            for field in field_defs:
                start = field['start']
                end = field['end']
                if start == end:
                    if start in bits:
                        print("    [{:>2d}]: {}".format(start, field['name']))
                        desc_lines = textwrap.wrap(field['desc'], width=72)
                        for line in desc_lines:
                            print("      {}".format(line))
                else:
                    intersection = set(range(start, end+1)).intersection(set(bits))
                    value = 0
                    for bit in intersection:
                        value |= 1 << (end - bit)
                    if field['name'] != "Reserved" or value != 0:
                        print("    [{:>2d}:{:>2d}]: {}: 0x{:x}".format(start, end, field['name'], value))
                        desc_lines = textwrap.wrap(field['desc'], width=72)
                        for line in desc_lines:
                            print("      {}".format(line))

def pr_brdg_ctl(name, data):
    fields = ("Bridge Control",)
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_root_sts(name, data):
    fields = ("Device Status", "Slot Status", "Link Status", "devCmdStatus", "devSecStatus")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_phb_sts(name, data):
    fields = ("PLSSR", "DMACSR")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_lem(name, data):
    fields = ("LEM_FIR_AR", "LEM_EMR", "LEM_WOF_R")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_phb_err(name, data):
    fields = ("PHB_ESR", "PHB_FESR", "PHB_ELR_0", "PHB_ELR_1")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_rxe_arb_err(name, data):
    fields = ("RXE_ARB_ESR", "RXE_ARB_FESR", "RXE_ARB_ELR_0", "RXE_ARB_ELR_1")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_rxe_tce_err(name, data):
    fields = ("RXE_TCE_ESR", "RXE_TCE_FESR", "RXE_TCE_ELR_0", "RXE_TCE_ELR_1")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_pbl_err(name, data):
    fields = ("PBL_ESR", "PBL_FESR", "PBL_ELR_0", "PBL_ELR_1")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_regb_err(name, data):
    fields = ("REGB_ESR", "REGB_FESR", "REGB_ELR_0", "REGB_ELR_1")
    print("{}:".format(name))
    pr_field_bits_be(fields, data)

def pr_pe_ab(name, data):
    fields = ("PE A",)
    print("{}:".format(name))
    pr_field_bits_be(fields, data[:1])
    tt = extract_bit_field_be(data[0], 5, 3)
    tt_dma_map = {
        0: "write",
        2: "read",
        3: "read response",
    }
    is_dma = tt in tt_dma_map.keys()
    is_mmio = tt in (4, 5)
    pe_b = int(data[1], 16)
    if is_dma:
        addr = (pe_b & 0x1fffffffffffffff)
        print("  DMA {} addr [60:0]: 0x{:016x}".format(tt_dma_map[tt], addr))
    if is_mmio:
        addr = (pe_b & 0x0000ffffffffffff)
        print("  MMIO {} addr [0:47]: 0x{:012x}".format("load" if tt == 4 else "store", addr))

def main():
    # Load the register bit information.
    for csv_filename in glob.iglob('./data/*/*.csv'):
        reg_name = Path(csv_filename).parts[-1].split('.')[0]
        if reg_name not in REGISTERS.keys():
            REGISTERS[reg_name] = []
        with open(csv_filename, newline='') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                # Assume it's from the PHB4 spec.
                bits_f, name_f, desc_f = "Bit", "Field Mnemonic", "Description"
                if "Bits" in row.keys():
                    # This is from the IODA2 spec.
                    bits_f, name_f, desc_f = row.keys()
                bits = [int(x) for x in row[bits_f].split(':')]
                start = bits[0]
                if len(bits) > 1:
                    end = bits[1]
                else:
                    end = bits[0]
                name = row[name_f]
                desc = row[desc_f]
                REGISTERS[reg_name].append({
                    'start': start,
                    'end': end,
                    'name': name,
                    'desc': desc,
                })

    printers = {
        'brdgCtl': pr_brdg_ctl,
        'RootSts': pr_root_sts,
        'PhbSts': pr_phb_sts,
        'Lem': pr_lem,
        'PhbErr': pr_phb_err,
        'RxeArbErr': pr_rxe_arb_err,
        'RxeTceErr': pr_rxe_tce_err,
        'PblErr': pr_pbl_err,
        'RegbErr': pr_regb_err,
    }
    header = re.compile(r"PHB4 PHB#[0-9]+ Diag-data \(Version: (?P<version>[0-9]+)\)")
    line_re = re.compile(r"\[\s*(?P<timestamp>[0-9]+.[0-9]+)\] (?P<text>.*)")
    message = re.compile(r"(?P<name>.*):\s+(?P<data>.*)")
    parsing_enabled = False
    for line in fileinput.input():
        text_match = line_re.match(line)
        if not text_match:
            continue
        text = text_match.groupdict()['text']
        header_match = header.fullmatch(text)
        if header_match:
            version = int(header_match.groupdict()['version'])
            assert version == 1
            print("-------")
            parsing_enabled = True
            continue
        if text.startswith("EEH"):
            #print("Stop parsing.")
            parsing_enabled = False
            continue
        if not parsing_enabled:
            continue
        info = message.match(text).groupdict()
        name = info['name']
        data = info['data'].split()
        if name.startswith("PE["):
            pr_pe_ab(name, data)
        else:
            printers.get(name, print)(name, data)


if __name__ == "__main__":
    main()
