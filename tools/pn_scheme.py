"""
R_Library Part Numbering Scheme
================================
Format: r#######-##-A
  r          : library prefix (Raheel's library)
  #######    : 7-digit part number (category + sequential)
  ##         : 2-digit variant (01 = primary, 02+ = alternate package/source)
  A          : version letter (always A for discrete parts; A/B/C/... for board assemblies)

Category Ranges:
  r1000001 - r1999999 : Resistors
  r2000001 - r2999999 : Capacitors
  r3000001 - r3999999 : Inductors & Magnetic / Ferrite Beads
  r4000001 - r4999999 : Diodes, Rectifiers & Protection (TVS, ESD)
  r5000001 - r5999999 : LEDs & Optoelectronics
  r6000001 - r6999999 : Transistors & MOSFETs
  r7000001 - r7999999 : Integrated Circuits (all U-reference parts)
  r8000001 - r8999999 : Connectors & Cables
  r9000001 - r9499999 : Crystals, Oscillators, Switches & Miscellaneous
  r9500001 - r9999999 : PCB Assemblies & Full Boards (version field active: A, B, C...)

Variant field (##):
  01 : Primary / most common variant
  02+: Alternate source, pin-compatible substitute, or different package of same value

Version field (A):
  Discrete parts (R/C/L/D/LED/Q/U/J/X/SW): Always 'A' — does not change
  Board assemblies (r9500001+): 'A' = first release, 'B' = rev B, etc.

Value field conventions by category:
  Resistors  : "<resistance> <tolerance> <power> <package>  e.g. 10kΩ 1% 1/16W 0402"
  Capacitors : "<capacitance> <voltage> <dielectric> <package>  e.g. 100nF 50V X7R 0402"
  Inductors  : "<inductance> <tolerance> <current> <package>  e.g. 4.7uH 20% 2.5A 252010"
  Diodes     : "<type> <voltage> <current> <package>  e.g. Schottky 40V 1A SOD-323"
  LEDs       : "<color> <Vf> <If> <package>  e.g. Red 2.0V 20mA 0603"
  Transistors: "<type> <Vceo> <Ic> <package>  e.g. NPN 40V 500mA SOT-23"
  ICs        : "<part_number> <brief_function>  e.g. RP2354B MCU"
  Connectors : "<type> <pitch> <pins>  e.g. JST-PH 2.0mm 4P"
  Crystals   : "<freq> <accuracy> <load_cap>  e.g. 32.768kHz ±20ppm 12.5pF"
  Boards     : "<board_name> <brief_description>"

The full PN is appended to the Value field: "... | r1000001-01-A"
"""

CATEGORY_BASES = {
    'R':    1_000_001,
    'C':    2_000_001,
    'L':    3_000_001,
    'D':    4_000_001,
    'LED':  5_000_001,
    'Q':    6_000_001,
    'U':    7_000_001,
    'J':    8_000_001,
    'CN':   8_100_001,
    'USB':  8_200_001,
    'Card': 8_300_001,
    'SW':   9_000_001,
    'X':    9_100_001,
    'MISC': 9_200_001,
    'PCB':  9_500_001,
}

CATEGORY_NAMES = {
    'R':    'Resistor',
    'C':    'Capacitor',
    'L':    'Inductor',
    'D':    'Diode/Protection',
    'LED':  'LED',
    'Q':    'Transistor/FET',
    'U':    'Integrated Circuit',
    'J':    'Connector',
    'CN':   'Connector',
    'USB':  'USB Connector',
    'Card': 'Card Connector',
    'SW':   'Switch',
    'X':    'Crystal/Oscillator',
    'MISC': 'Miscellaneous',
    'PCB':  'PCB Assembly',
}


def format_pn(number: int, variant: int = 1, version: str = 'A') -> str:
    return f"r{number:07d}-{variant:02d}-{version}"


def next_pn(registry: dict, ref_type: str, variant: int = 1, version: str = 'A') -> str:
    cat = ref_type if ref_type in CATEGORY_BASES else 'MISC'
    base = CATEGORY_BASES[cat]
    used = {int(pn[1:8]) for pn in registry.get('parts', {}).values()
            if pn.startswith('r') and int(pn[1:8]) >= base and int(pn[1:8]) < base + 100_000}
    n = base
    while n in used:
        n += 1
    return format_pn(n, variant, version)
