"""
build_library.py
Converts easyeda2kicad.kicad_sym → R_Library.kicad_sym with:
  - Value  = original manufacturer part number (unchanged)
  - Description = enriched human-readable spec (decoded from part number or source)
  - Part Number property added and VISIBLE on schematic
  - Value1 EasyEDA artefact removed
  - Footprint references updated easyeda2kicad → R_Library
  - pn_registry.json keeps numbers stable across runs

Usage:
  python build_library.py [--dry-run] [--sample-only]
"""

import re, json, sys
from pathlib import Path
from pn_scheme import format_pn, CATEGORY_BASES, CATEGORY_NAMES

ROOT       = Path(__file__).parent.parent
SRC_SYM    = ROOT.parent / "easyeda2kicad" / "easyeda2kicad.kicad_sym"
DST_SYM    = ROOT / "R_Library.kicad_sym"
REGISTRY   = ROOT / "pn_registry.json"

# ── registry ──────────────────────────────────────────────────────────────────

def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    return {"parts": {}, "counters": {}}

def save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding='utf-8')

def alloc_pn(reg: dict, sym_name: str, ref_type: str, variant: int = 1, version: str = 'A') -> str:
    if sym_name in reg["parts"]:
        return reg["parts"][sym_name]
    cat = ref_type if ref_type in CATEGORY_BASES else 'MISC'
    key = f"counter_{cat}"
    n = reg["counters"].get(key, CATEGORY_BASES[cat])
    pn = format_pn(n, variant, version)
    reg["counters"][key] = n + 1
    reg["parts"][sym_name] = pn
    return pn

# ── block helpers ─────────────────────────────────────────────────────────────

def _get_prop(block: str, name: str) -> str:
    m = re.search(rf'\(property "{re.escape(name)}" "([^"]*)"', block)
    return m.group(1).strip() if m else ""

def _set_prop(block: str, name: str, new_value: str) -> str:
    pattern = rf'(\(property "{re.escape(name)}" )"([^"]*)"'
    if re.search(pattern, block):
        return re.sub(pattern, rf'\1"{new_value}"', block, count=1)
    return block

def _remove_prop(block: str, name: str) -> str:
    """Remove an entire named property block (handles nested parens)."""
    marker = f'(property "{name}"'
    idx = block.find(marker)
    if idx < 0:
        return block
    line_start = block.rfind('\n', 0, idx) + 1  # start of the property's line
    depth, i, in_str = 0, idx, False
    while i < len(block):
        c = block[i]
        if c == '"' and (i == 0 or block[i-1] != '\\'):
            in_str = not in_str
        if not in_str:
            if c == '(':   depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    if end < len(block) and block[end] == '\n':
                        end += 1
                    break
        i += 1
    else:
        return block
    return block[:line_start] + block[end:]

def _value_y(block: str) -> float:
    """Return Y coordinate of the Value property (used to place PN below it)."""
    m = re.search(r'\(property "Value" "[^"]*"\s*\(at [\d.-]+ ([\d.-]+)', block)
    return float(m.group(1)) if m else -5.08

# ── description builders ──────────────────────────────────────────────────────
# These return a description string (no PN appended — that goes in Part Number field).

def _decode_resistance(sym_name: str, desc: str) -> str:
    m = re.search(r'([\d.]+)\s*(K|M|G|m)?\s*OHM', desc, re.I)
    if m:
        val, mult = float(m.group(1)), (m.group(2) or "").upper()
        if mult == 'K':   return f"{val:g}kΩ"
        elif mult == 'M': return f"{val:g}MΩ"
        elif mult == 'G': return f"{val:g}GΩ"
        elif mult == 'm': return f"{val:g}mΩ"
        else:             return f"{val:g}Ω"
    # 4-digit EIA code (≥10Ω): 3 mantissa + 1 exp digit
    mr = re.search(r'[A-Z](\d{3})([0-9])(?:TCE|JCE|T5E|BRE|TS\b)', sym_name.upper())
    if mr:
        ohms = int(mr.group(1)) * (10 ** int(mr.group(2)))
        if ohms == 0:          return "0Ω (DNP)"
        elif ohms < 1000:      return f"{ohms}Ω"
        elif ohms < 1_000_000: return f"{ohms/1000:g}kΩ"
        else:                  return f"{ohms/1_000_000:g}MΩ"
    # 3-digit EIA code (<10Ω): 2 mantissa + 1 exp, then tolerance letter
    mr2 = re.search(r'[A-Z](\d{2})(\d)[FJBCDE](?:TCE|T5E)', sym_name.upper())
    if mr2:
        ohms = int(mr2.group(1)) * (10 ** int(mr2.group(2)))
        if ohms == 0:          return "0Ω (DNP)"
        elif ohms < 1000:      return f"{ohms}Ω"
        elif ohms < 1_000_000: return f"{ohms/1000:g}kΩ"
        else:                  return f"{ohms/1_000_000:g}MΩ"
    return ""

_PKG_R = r'(?<!\d)(0201|0402|0603|0805|1206|1210|2010|2512)(?!\d)'
_PKG_C = r'(?<!\d)(0201|0402|0603|0805|1206|1210|1812)(?!\d)'

def build_resistor_desc(sym_name: str, existing_desc: str) -> str:
    resistance = _decode_resistance(sym_name, existing_desc)
    tolerance  = ""
    power      = ""
    package    = ""

    m = re.search(r'(\d+\.?\d*%)', existing_desc, re.I)
    if m: tolerance = m.group(1)
    m = re.search(r'(\d+/\d+W|\d+W)', existing_desc, re.I)
    if m: power = m.group(1)
    m = re.search(_PKG_R, existing_desc, re.I) or re.search(_PKG_R, sym_name, re.I)
    if m: package = m.group(1)

    parts = [x for x in [package, resistance, tolerance, power] if x]
    if parts:
        return "Resistor " + " ".join(parts)
    return existing_desc  # fallback to original

def build_capacitor_desc(sym_name: str, existing_desc: str) -> str:
    cap = voltage = dielectric = tolerance = package = ""

    m = re.search(r'([\d.]+)\s*(MF|UF|NF|PF|F)\b', existing_desc, re.I)
    if m:
        val, unit = float(m.group(1)), m.group(2).upper()
        cap = {"MF": f"{val:g}mF", "UF": f"{val:g}µF", "NF": f"{val:g}nF",
               "PF": f"{val:g}pF", "F": f"{val:g}F"}.get(unit, "")
    m = re.search(r'([\d.]+)\s*V\b', existing_desc, re.I)
    if m: voltage = f"{m.group(1)}V"
    m = re.search(r'\b(X7R|X5R|C0G|NP0|Y5V|Z5U|X8R|X6S)\b', existing_desc, re.I)
    if m: dielectric = m.group(1).upper()
    m = re.search(r'(\d+\.?\d*%)', existing_desc, re.I)
    if m: tolerance = m.group(1)
    m = re.search(_PKG_C, existing_desc, re.I) or re.search(_PKG_C, sym_name, re.I)
    if m: package = m.group(1)

    parts = [x for x in [package, cap, voltage, dielectric, tolerance] if x]
    if parts:
        return "Capacitor " + " ".join(parts)
    return existing_desc

def build_generic_desc(sym_name: str, existing_desc: str) -> str:
    """For everything else: keep existing description, don't override."""
    return existing_desc

DESC_BUILDERS = {
    'R':    build_resistor_desc,
    'C':    build_capacitor_desc,
}

def build_desc(ref: str, sym_name: str, existing_desc: str) -> str:
    builder = DESC_BUILDERS.get(ref, build_generic_desc)
    return builder(sym_name, existing_desc)

# ── symbol parser ─────────────────────────────────────────────────────────────

def parse_symbols(content: str):
    for m in re.finditer(r'\n\t\(symbol "([^"]+)"\s*\n\t\t\(exclude_from_sim', content):
        name  = m.group(1)
        start = m.start() + 1
        depth, i, in_string = 0, start, False
        while i < len(content):
            c = content[i]
            if c == '"' and (i == 0 or content[i-1] != '\\'):
                in_string = not in_string
            if not in_string:
                if c == '(':   depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1; break
            i += 1
        else:
            continue
        block = content[start:end]
        yield name, start, end, _get_prop(block,'Reference'), _get_prop(block,'Value'), \
              _get_prop(block,'Description'), _get_prop(block,'Footprint'), block

# ── main ──────────────────────────────────────────────────────────────────────

def process(dry_run=False, sample_only=False):
    reg = load_registry()
    src = SRC_SYM.read_text(encoding='utf-8')

    new_header = src[:src.index('\n\t(symbol ')]
    new_header = new_header.replace(
        '(generator "kicad_symbol_editor")',
        '(generator "R_Library_build_script")'
    )

    symbols_seen = {}
    out_blocks   = []

    for name, start, end, ref, orig_val, orig_desc, footprint, block in parse_symbols(src):
        pn = alloc_pn(reg, name, ref)

        # Value = original MPN (no change)
        # Description = decoded spec (for R/C) or kept as-is
        new_desc = build_desc(ref, name, orig_desc)
        new_fp   = footprint.replace('easyeda2kicad:', 'R_Library:')

        new_block = block
        # Value stays as the MPN — restore it to the original symbol name in case
        # a previous run had put the enriched string there
        new_block = _set_prop(new_block, 'Value', name)
        new_block = _set_prop(new_block, 'Description', new_desc)
        new_block = _set_prop(new_block, 'Footprint', new_fp)

        # Remove Value1 EasyEDA artefact
        new_block = _remove_prop(new_block, 'Value1')

        # Add Part Number property (visible on schematic) before the sub-symbol
        if '"Part Number"' not in new_block:
            sub_sym = re.search(r'\n\t\t\(symbol "', new_block)
            if sub_sym:
                insert_pos = sub_sym.start() + 1
                y = _value_y(new_block) - 2.54
                pn_prop = (
                    f'\t\t(property "Part Number" "{pn}"\n'
                    f'\t\t\t(at 0 {y:.3f} 0)\n'
                    f'\t\t\t(show_name no)\n'
                    f'\t\t\t(do_not_autoplace no)\n'
                    f'\t\t\t(effects\n'
                    f'\t\t\t\t(font\n'
                    f'\t\t\t\t\t(size 1.27 1.27)\n'
                    f'\t\t\t\t)\n'
                    f'\t\t\t)\n'
                    f'\t\t)\n'
                )
                new_block = new_block[:insert_pos] + pn_prop + new_block[insert_pos:]
        else:
            # If PN property already exists, make sure it isn't hidden
            new_block = re.sub(
                r'(\(property "Part Number" "[^"]*"(?:(?!\(property).)*?)\(hide yes\)',
                r'\1',
                new_block, flags=re.DOTALL
            )

        out_blocks.append(new_block)

        if sample_only and ref not in symbols_seen:
            symbols_seen[ref] = True
            def p(s): print(s.encode('ascii', 'replace').decode('ascii'))
            p(f"\n{'='*60}")
            p(f"[{ref}] {name}")
            p(f"  Value (MPN)  : {name}")
            p(f"  Desc (new)   : {new_desc}")
            p(f"  Part Number  : {pn}")
            p(f"  Footprint    : {new_fp}")

    if sample_only:
        print(f"\nTotal: {len(out_blocks)} symbols")
        return

    if not dry_run:
        full_content = new_header + '\n' + '\n'.join(out_blocks) + '\n)\n'
        DST_SYM.write_bytes(full_content.encode('utf-8'))   # write_bytes = no BOM
        save_registry(reg)
        print(f"Written {DST_SYM}")
        print(f"Registry: {len(reg['parts'])} parts")
    else:
        print(f"[dry-run] {len(out_blocks)} symbols → {DST_SYM}")

if __name__ == '__main__':
    dry  = '--dry-run'     in sys.argv
    samp = '--sample-only' in sys.argv
    process(dry_run=dry, sample_only=samp)
