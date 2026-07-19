"""
R_Library Manager
==================
CLI tool for managing the R_Library KiCad parts library.

Commands:
  search  <query>            Search parts by name, value, description, or PN
  list    [category]         List all parts (optionally filtered by category)
  info    <MPN-or-PN>        Show full details for a part
  import  <LCSC-ID>          Import a part from LCSC via easyeda2kicad and add to R_Library
  add-board <name> <desc>    Register a new PCB assembly with the next board PN
  rebuild                    Rebuild R_Library.kicad_sym from easyeda2kicad source

Examples:
  python library_manager.py search 10k
  python library_manager.py search r2000001
  python library_manager.py list R
  python library_manager.py info 0402WGF1001TCE
  python library_manager.py import C2977777
  python library_manager.py add-board "Iris Sensor Board" "Rev A mainboard for Iris project"
"""

import re, json, sys, os, subprocess, shutil, argparse
from pathlib import Path

ROOT      = Path(__file__).parent.parent
SYM_FILE  = ROOT / "R_Library.kicad_sym"
REGISTRY  = ROOT / "pn_registry.json"
TOOLS_DIR = Path(__file__).parent
SRC_DIR   = ROOT.parent / "easyeda2kicad"

sys.stdout.reconfigure(encoding='utf-8')

# ── registry helpers ──────────────────────────────────────────────────────────

def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding='utf-8-sig'))
    return {"parts": {}, "counters": {}}

def save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding='utf-8')

# ── symbol parser ─────────────────────────────────────────────────────────────

def _get_prop(block: str, name: str) -> str:
    # KiCad 10 format: (property "Name" "Value" ...)
    m = re.search(rf'\(property "{re.escape(name)}" "([^"]*)"', block)
    if m:
        return m.group(1).strip()
    # Old easyeda2kicad format: (property\n  "Name"\n  "Value"\n ...)
    m = re.search(rf'\(property\s*\n\s*"{re.escape(name)}"\s*\n\s*"([^"]*)"', block)
    return m.group(1).strip() if m else ""

def _set_prop(block: str, name: str, new_value: str) -> str:
    # KiCad 10 format
    pattern = rf'(\(property "{re.escape(name)}" )"([^"]*)"'
    if re.search(pattern, block):
        return re.sub(pattern, rf'\1"{new_value}"', block, count=1)
    # Old easyeda2kicad multiline format
    pattern_old = rf'(\(property\s*\n\s*"{re.escape(name)}"\s*\n\s*)"([^"]*)"'
    if re.search(pattern_old, block):
        return re.sub(pattern_old, rf'\g<1>"{new_value}"', block, count=1)
    return block

def _prop_pos(block: str, name: str) -> tuple[float, float]:
    """(x, y) of a property's (at ...) coordinate, in either symbol format."""
    m = re.search(rf'\(property "{re.escape(name)}" "[^"]*"\s*\n\s*\(at ([\d.-]+) ([\d.-]+)', block)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(
        rf'\(property\s*\n\s*"{re.escape(name)}"\s*\n\s*"[^"]*"\s*\n\s*\(id \d+\)\s*\n\s*\(at ([\d.-]+) ([\d.-]+)',
        block
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    return (0.0, -5.08)

def _ensure_prop(block: str, name: str, value: str) -> str:
    """Set property `name` to `value`; insert a new hidden property before the
    first sub-symbol if it doesn't exist in the block yet."""
    if f'(property "{name}"' in block or re.search(rf'\(property\s*\n\s*"{re.escape(name)}"', block):
        return _set_prop(block, name, value)
    sub_sym = re.search(r'\n(\t\t|    )\(symbol "', block)
    if not sub_sym:
        return block
    ip     = sub_sym.start() + 1
    indent = sub_sym.group(1)
    if '\t' in indent:  # KiCad-10 style
        prop = (
            f'\t\t(property "{name}" "{value}"\n'
            f'\t\t\t(at 0 0 0)\n\t\t\t(show_name no)\n'
            f'\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n'
            f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            f'\t\t\t\t)\n\t\t\t)\n\t\t)\n'
        )
    else:               # old easyeda2kicad 2-space style
        prop = (
            f'    (property\n'
            f'      "{name}"\n'
            f'      "{value}"\n'
            f'      (id 99)\n'
            f'      (at 0 0 0)\n'
            f'      (effects (font (size 1.27 1.27) ) hide)\n'
            f'    )\n'
        )
    return block[:ip] + prop + block[ip:]

def parse_all_symbols(content: str) -> list[dict]:
    results = []
    # Match top-level symbols with either tab (KiCad 10) or 2-space (old easyeda2kicad) indent
    # Skip sub-symbols whose names end with _N_N (e.g. "RTL8201F-VB-CG_0_1")
    for m in re.finditer(r'\n(\t|  )\(symbol "([^"]+)"', content):
        name = m.group(2)
        if re.search(r'_\d+_\d+$', name):
            continue
        start = m.start() + 1
        depth, i, in_string = 0, start, False
        while i < len(content):
            c = content[i]
            if c == '"' and (i == 0 or content[i-1] != '\\'):
                in_string = not in_string
            if not in_string:
                if c == '(':    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            i += 1
        else:
            continue
        block = content[start:end]
        results.append({
            'name':        name,
            'start':       start,
            'end':         end,
            'ref':         _get_prop(block, 'Reference'),
            'value':       _get_prop(block, 'Value'),
            'description': _get_prop(block, 'Description'),
            'footprint':   _get_prop(block, 'Footprint'),
            'datasheet':   _get_prop(block, 'Datasheet'),
            'part_number': _get_prop(block, 'Part Number'),
            'lcsc':        _get_prop(block, 'LCSC Part'),
            'block':       block,
        })
    return results

def load_library() -> tuple[str, list[dict]]:
    content = SYM_FILE.read_text(encoding='utf-8')
    return content, parse_all_symbols(content)

# ── search ────────────────────────────────────────────────────────────────────

CATEGORY_NAMES = {
    'R': 'Resistor', 'C': 'Capacitor', 'L': 'Inductor', 'D': 'Diode',
    'LED': 'LED', 'Q': 'Transistor/FET', 'U': 'IC', 'J': 'Connector',
    'CN': 'Connector', 'USB': 'USB Conn', 'Card': 'Card Conn',
    'SW': 'Switch', 'X': 'Crystal/Osc',
}

def cmd_search(query: str):
    _, symbols = load_library()
    q = query.lower()
    hits = []
    for s in symbols:
        fields = [s['name'], s['value'], s['description'], s['part_number'], s['lcsc']]
        if any(q in (f or '').lower() for f in fields):
            hits.append(s)

    if not hits:
        print(f"No parts found matching '{query}'")
        return

    print(f"\n{'PN':<22} {'Ref':<5} {'MPN':<30} {'Value / Description'}")
    print('-' * 100)
    for s in hits:
        cat = CATEGORY_NAMES.get(s['ref'], s['ref'])
        val = s['value'][:55] if s['value'] else ''
        pn  = s['part_number'] or '—'
        print(f"{pn:<22} {s['ref']:<5} {s['name']:<30} {val}")
    print(f"\n{len(hits)} result(s)")

# ── list ──────────────────────────────────────────────────────────────────────

def cmd_list(category: str | None):
    _, symbols = load_library()
    if category:
        symbols = [s for s in symbols if s['ref'].upper() == category.upper()]
        if not symbols:
            print(f"No parts found with reference '{category}'")
            return

    print(f"\n{'PN':<22} {'Ref':<5} {'MPN':<35} {'Value'}")
    print('-' * 105)
    for s in sorted(symbols, key=lambda x: (x['ref'], x['part_number'] or '')):
        pn  = s['part_number'] or '—'
        val = s['value'][:48] if s['value'] else ''
        print(f"{pn:<22} {s['ref']:<5} {s['name']:<35} {val}")
    print(f"\nTotal: {len(symbols)} parts")

# ── info ──────────────────────────────────────────────────────────────────────

def cmd_info(query: str):
    _, symbols = load_library()
    q = query.lower()
    match = None
    for s in symbols:
        if q in (s['name'] or '').lower() or q in (s['part_number'] or '').lower():
            match = s
            break
    if not match:
        print(f"Part not found: {query}")
        return
    print()
    print(f"  MPN         : {match['name']}")
    print(f"  Part Number : {match['part_number'] or '(not assigned)'}")
    print(f"  Reference   : {match['ref']}")
    print(f"  Value       : {match['value']}")
    print(f"  Footprint   : {match['footprint']}")
    print(f"  Description : {match['description']}")
    print(f"  LCSC Part   : {match['lcsc']}")
    print(f"  Datasheet   : {match['datasheet']}")
    print()

# ── import from easyeda2kicad ─────────────────────────────────────────────────

def _check_easyeda2kicad():
    result = shutil.which('easyeda2kicad') or shutil.which('easyeda2kicad.exe')
    if not result:
        # try pip-installed entry point
        try:
            subprocess.run(['python', '-m', 'easyeda2kicad', '--help'],
                           capture_output=True, timeout=5)
            return ['python', '-m', 'easyeda2kicad']
        except Exception:
            pass
        raise RuntimeError(
            "easyeda2kicad not found. Install with:\n"
            "  pip install easyeda2kicad"
        )
    return [result]

# ── LCSC spec enrichment (passives) ───────────────────────────────────────────
# The local MPN decoder in build_library can't parse every passive (current-sense
# shunts, specialty resistors) and easyeda descriptions are often blank. For R/C
# parts we scrape the structured spec table off the LCSC product page to build a
# proper Value/Description per SPEC.md §4/§5, falling back to the local decode.

_POWER_FRAC = {
    '62.5mW': '1/16W', '63mW': '1/16W', '100mW': '1/10W', '125mW': '1/8W',
    '150mW': '3/20W',  '200mW': '1/5W',  '250mW': '1/4W',  '333mW': '1/3W',
    '500mW': '1/2W',   '600mW': '3/5W',  '750mW': '3/4W',
}

def _fetch_lcsc_params(lcsc_id: str) -> tuple:
    """Scrape spec data from the LCSC product page's embedded Next.js
    __NEXT_DATA__ JSON. Returns (encap, {param: value}, category_path); on any
    failure returns ('', {}, '') so callers fall back gracefully — never raises."""
    try:
        import requests
        from fake_useragent import UserAgent
        ua  = UserAgent(platforms='desktop').random
        url = f'https://www.lcsc.com/product-detail/{lcsc_id}.html'
        r = requests.get(url, headers={'User-Agent': ua, 'Accept': 'text/html'}, timeout=20)
        if r.status_code != 200:
            return '', {}, ''
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if not m:
            return '', {}, ''
        data = json.loads(m.group(1))
        def walk(o):
            if isinstance(o, dict):
                if 'paramVOList' in o:
                    yield o
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        node = next(walk(data), None)
        if not node:
            return '', {}, ''
        params = {p.get('paramNameEn'): p.get('paramValueEn')
                  for p in (node.get('paramVOList') or []) if p.get('paramNameEn')}
        crumbs = [c.get('catalogNameEn') for c in (node.get('parentCatalogList') or [])]
        crumbs.append(node.get('catalogName') or '')
        category = ' / '.join(c for c in crumbs if c)
        return (node.get('encapStandard') or ''), params, category
    except Exception:
        return '', {}, ''

# Coarse family used to compare an easyeda2kicad reference against the reference
# inferred from the LCSC category — all connector refs collapse to one family.
_REF_FAMILY = {'J': 'CONN', 'CN': 'CONN', 'USB': 'CONN', 'Card': 'CONN'}

def _ref_family(ref: str) -> str:
    return _REF_FAMILY.get(ref, ref)

def _lcsc_category_ref(category: str) -> str:
    """Map an LCSC category path to the expected R_Library reference designator.
    Returns '' when the category isn't confidently recognized (no warning then)."""
    c = (category or '').lower()
    if not c:
        return ''
    if 'crystal' in c or 'oscillator' in c or 'resonator' in c:
        return 'X'
    if 'inductor' in c or 'ferrite' in c or 'choke' in c or 'common mode' in c:
        return 'L'
    if 'resistor' in c:
        return 'R'
    if 'capacitor' in c:
        return 'C'
    if 'light emitting' in c or 'optoelectronic' in c:
        return 'LED'
    if 'diode' in c or 'tvs' in c or 'rectifier' in c or 'esd' in c or 'transient' in c:
        return 'D'
    if 'mosfet' in c or 'transistor' in c or 'igbt' in c or 'jfet' in c:
        return 'Q'
    if 'connector' in c or 'interconnect' in c or 'terminal' in c or 'header' in c:
        if 'usb' in c:
            return 'USB'
        if 'memory card' in c or 'sd card' in c or 'card socket' in c or 'card connector' in c:
            return 'Card'
        return 'CN'
    if 'switch' in c:
        return 'SW'
    if 'integrated circuit' in c or '(ics)' in c or 'microcontroller' in c:
        return 'U'
    return ''

def _clean_tol(t: str) -> str:
    return (t or '').replace('±', '').strip()

def _norm_power(p: str) -> str:
    p = (p or '').strip()
    if not p or p == '-':
        return ''
    return _POWER_FRAC.get(p, p)   # 100mW -> 1/10W; 3W stays 3W

def build_passive_from_lcsc(ref: str, encap: str, params: dict) -> tuple:
    """Build (Value, Description) for an R/C part from LCSC params, per SPEC.md
    §4/§5. Returns (None, None) if the essential value is missing."""
    pkg = (encap or '').strip()
    if ref == 'R':
        res = (params.get('Resistance') or '').strip()
        if not res:
            return None, None
        tol     = _clean_tol(params.get('Tolerance'))
        pwr     = _norm_power(params.get('Power(Watts)'))
        typ     = params.get('Type') or ''
        is_zero = res in ('0Ω', '0mΩ', '0R', '0')
        parts   = [pkg, res]
        if tol and not is_zero:      # 0Ω omits tolerance (SPEC §4)
            parts.append(tol)
        if pwr:
            parts.append(pwr)
        value = ' '.join(x for x in parts if x)
        if 'Current Sense' in typ or 'Shunt' in typ:
            desc = f'Shunt {value} current-sense'
        else:
            desc = f'Resistor {value}'
        return value, desc
    if ref == 'C':
        cap = (params.get('Capacitance') or '').strip()
        if not cap:
            return None, None
        volt = (params.get('Voltage Rating') or '').strip()
        diel = (params.get('Temperature Coefficient') or '').strip()
        tol  = _clean_tol(params.get('Tolerance'))
        parts = [pkg, cap] + [x for x in (volt, diel, tol) if x and x != '-']
        value = ' '.join(parts)
        return value, f'Capacitor {value}'
    return None, None

def cmd_import(lcsc_id: str):
    """Import a part from LCSC via easyeda2kicad and add it to R_Library."""
    lcsc_id = lcsc_id.upper()
    if not lcsc_id.startswith('C'):
        lcsc_id = 'C' + lcsc_id

    # Check if already in library
    reg = load_registry()
    _, symbols = load_library()
    for s in symbols:
        if (s['lcsc'] or '').upper() == lcsc_id:
            print(f"Part {lcsc_id} already in R_Library as {s['name']} ({s['part_number']})")
            return

    print(f"Importing {lcsc_id} via easyeda2kicad...")
    cmd = _check_easyeda2kicad()

    # Run easyeda2kicad into the default source location (no --output).
    # This appends to easyeda2kicad.kicad_sym and copies footprint/3D to matching dirs.
    run_args = cmd + ['--lcsc_id', lcsc_id, '--full', '--overwrite']
    result = subprocess.run(run_args, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"easyeda2kicad failed:\n{result.stderr or result.stdout}")
        return

    # Parse the source library to find the newly added symbol by LCSC ID
    src_sym_file = SRC_DIR / 'easyeda2kicad.kicad_sym'
    src_content  = src_sym_file.read_text(encoding='utf-8')
    src_symbols  = parse_all_symbols(src_content)

    imp_symbols = [s for s in src_symbols if (s['lcsc'] or '').upper() == lcsc_id]
    if not imp_symbols:
        print(f"Could not find {lcsc_id} in source library after import.")
        return

    from build_library import alloc_pn, build_value, build_desc

    new_blocks = []
    category_warnings = []
    for s in imp_symbols:
        blk  = s['block']
        name = s['name']

        # Strip trailing LCSC-ID artifact suffix (e.g. "CH340N_C2977777" ->
        # "CH340N"), but only when the suffix really is the LCSC ID, not part
        # of the real MPN.
        m = re.search(r'[-_](C\d+)$', name)
        if m and m.group(1).upper() == (s['lcsc'] or '').upper():
            clean_name = name[:m.start()]
            blk  = blk.replace(name, clean_name)
            name = clean_name

        pn      = alloc_pn(reg, name, s['ref'])
        new_fp  = (s['footprint']
                   .replace('easyeda2kicad:', 'R_Library:')
                   .replace('imported:', 'R_Library:'))

        # Fetch LCSC structured data once — reused for passive Value/Description
        # enrichment and for the category/reference sanity check below.
        lcsc_enc, lcsc_params, lcsc_category = '', {}, ''
        if s['lcsc']:
            lcsc_enc, lcsc_params, lcsc_category = _fetch_lcsc_params(s['lcsc'])

        # Value: decoded spec for R/C per SPEC.md §4 ("<pkg> <val> <tol> ..."),
        # MPN for everything else. Falls back to the MPN if it can't be decoded.
        new_val  = build_value(s['ref'], name, s['description'])
        new_desc = build_desc(s['ref'], name, s['description']) or name

        # Passives: prefer LCSC's structured specs (fuller + handles parts the
        # local decoder can't). Silently falls back to the local decode.
        if s['ref'] in ('R', 'C'):
            lv, ld = build_passive_from_lcsc(s['ref'], lcsc_enc, lcsc_params)
            if lv:
                new_val, new_desc = lv, ld
                print(f"    LCSC specs -> {lv}")

        # Category sanity check: easyeda2kicad often mis-assigns the reference
        # (e.g. 'U' to a connector). Warn when the LCSC category disagrees so it
        # can be recategorized + re-allocated into the right PN range (SPEC §1).
        expected_ref = _lcsc_category_ref(lcsc_category)
        if expected_ref and _ref_family(expected_ref) != _ref_family(s['ref']):
            category_warnings.append((name, s['ref'], pn, expected_ref, lcsc_category))

        blk = _set_prop(blk, 'Value', new_val)
        blk = _set_prop(blk, 'Footprint', new_fp)

        # Description must exist and be non-empty (SPEC.md §5).
        blk = _ensure_prop(blk, 'Description', new_desc)

        # Datasheet: fall back to the LCSC product page when left blank.
        if not _get_prop(blk, 'Datasheet').strip() and s['lcsc']:
            lcsc_url = f'https://www.lcsc.com/product-detail/{s["lcsc"]}.html'
            blk = _ensure_prop(blk, 'Datasheet', lcsc_url)

        # Add Part Number property before the first sub-symbol definition:
        # visible, positioned 2.54mm below Value (SPEC.md section 3).
        if '"Part Number"' not in blk:
            sub_sym = re.search(r'\n(\t\t|    )\(symbol "', blk)
            if sub_sym:
                ip     = sub_sym.start() + 1
                indent = sub_sym.group(1)
                vx, vy = _prop_pos(blk, 'Value')
                y = vy - 2.54
                if '\t' in indent:  # KiCad-10 style
                    pn_prop = (
                        f'\t\t(property "Part Number" "{pn}"\n'
                        f'\t\t\t(at {vx:g} {y:g} 0)\n\t\t\t(show_name no)\n'
                        f'\t\t\t(do_not_autoplace no)\n'
                        f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
                        f'\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                    )
                else:               # old easyeda2kicad 2-space style
                    pn_prop = (
                        f'    (property\n'
                        f'      "Part Number"\n'
                        f'      "{pn}"\n'
                        f'      (id 99)\n'
                        f'      (at {vx:g} {y:g} 0)\n'
                        f'      (effects (font (size 1.27 1.27) ) )\n'
                        f'    )\n'
                    )
                blk = blk[:ip] + pn_prop + blk[ip:]

        new_blocks.append(blk)
        print(f"  {name} -> {pn}")

    # Merge into R_Library.kicad_sym
    content = SYM_FILE.read_text(encoding='utf-8')
    if content.rstrip().endswith(')'):
        content = content.rstrip()[:-1].rstrip() + '\n'
    content += '\n' + '\n'.join(new_blocks) + '\n)\n'
    SYM_FILE.write_text(content, encoding='utf-8')

    # Copy footprints from easyeda2kicad source → R_Library
    src_fp_dir  = SRC_DIR / 'easyeda2kicad.pretty'
    src_3d_dir  = SRC_DIR / 'easyeda2kicad.3dshapes'
    dst_fp_dir  = ROOT / 'R_Library.pretty'
    dst_3d_dir  = ROOT / 'R_Library.3dshapes'

    # Determine which footprint name belongs to this symbol
    fp_name = new_blocks[0] and re.search(r'\(property.*?"Footprint".*?"R_Library:([^"]+)"', new_blocks[0], re.DOTALL)
    fp_stem = fp_name.group(1) if fp_name else None

    for fp_file in src_fp_dir.glob('*.kicad_mod') if src_fp_dir.exists() else []:
        if fp_stem and fp_file.stem != fp_stem:
            continue  # only copy the footprint for this part
        dst = dst_fp_dir / fp_file.name
        if dst.exists():
            # Shared package already present — keep the curated version (SPEC §7),
            # never clobber it with the raw easyeda2kicad footprint.
            print(f"  Footprint : {fp_file.name} (kept existing, not overwritten)")
            continue
        fp_text = fp_file.read_text(encoding='utf-8')
        fp_text = fp_text.replace('easyeda2kicad.3dshapes', 'R_Library.3dshapes')
        dst.write_text(fp_text, encoding='utf-8')
        print(f"  Footprint : {fp_file.name}")

    for m3d_file in (src_3d_dir.iterdir() if src_3d_dir.exists() else []):
        dst = dst_3d_dir / m3d_file.name
        if not dst.exists():
            shutil.copy2(str(m3d_file), str(dst))
            print(f"  3D model  : {m3d_file.name}")

    save_registry(reg)
    print(f"\nSuccessfully imported {lcsc_id} into R_Library.")

    for nm, got, gpn, want, cat in category_warnings:
        print( "\n" + "!" * 68)
        print(f"  CATEGORY MISMATCH: {nm} ({gpn})")
        print(f"    easyeda2kicad assigned reference '{got}', but LCSC category is:")
        print(f"      {cat}")
        print(f"    -> expected reference '{want}'. Recategorize and re-allocate the")
        print(f"       PN into the '{want}' range before committing (SPEC.md §1).")
        print( "!" * 68)

# ── add-board ─────────────────────────────────────────────────────────────────

def cmd_add_board(name: str, description: str):
    from pn_scheme import CATEGORY_BASES, format_pn
    reg = load_registry()
    key = 'counter_PCB'
    n = reg['counters'].get(key, CATEGORY_BASES['PCB'])
    pn = format_pn(n, 1, 'A')
    reg['counters'][key] = n + 1
    reg['parts'][f'BOARD:{name}'] = pn
    save_registry(reg)
    print(f"\nBoard registered:")
    print(f"  Name       : {name}")
    print(f"  Description: {description}")
    print(f"  Part Number: {pn}")
    print(f"\nNext revision (when needed): {pn[:-1]}B")

# ── rebuild ───────────────────────────────────────────────────────────────────

def cmd_rebuild():
    print("Rebuilding R_Library.kicad_sym from easyeda2kicad source...")
    build_script = TOOLS_DIR / 'build_library.py'
    result = subprocess.run(
        ['python', str(build_script)],
        capture_output=True, text=True
    )
    print(result.stdout or result.stderr)

# ── CLI entry ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='R_Library Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    sub = parser.add_subparsers(dest='command')

    p_search = sub.add_parser('search', help='Search parts by any field')
    p_search.add_argument('query', help='Search term (name, value, PN, LCSC ID)')

    p_list = sub.add_parser('list', help='List all parts')
    p_list.add_argument('category', nargs='?', help='Filter by reference (R, C, U, ...)')

    p_info = sub.add_parser('info', help='Show full details for a part')
    p_info.add_argument('query', help='MPN or part number')

    p_import = sub.add_parser('import', help='Import part from LCSC via easyeda2kicad')
    p_import.add_argument('lcsc_id', help='LCSC part ID (e.g. C2977777 or just 2977777)')

    p_board = sub.add_parser('add-board', help='Register a new PCB assembly')
    p_board.add_argument('name', help='Board name')
    p_board.add_argument('description', help='Brief description')

    sub.add_parser('rebuild', help='Rebuild library from easyeda2kicad source')

    args = parser.parse_args()

    if args.command == 'search':
        cmd_search(args.query)
    elif args.command == 'list':
        cmd_list(getattr(args, 'category', None))
    elif args.command == 'info':
        cmd_info(args.query)
    elif args.command == 'import':
        cmd_import(args.lcsc_id)
    elif args.command == 'add-board':
        cmd_add_board(args.name, args.description)
    elif args.command == 'rebuild':
        cmd_rebuild()
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
