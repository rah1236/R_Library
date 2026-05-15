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
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    return {"parts": {}, "counters": {}}

def save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding='utf-8')

# ── symbol parser ─────────────────────────────────────────────────────────────

def _get_prop(block: str, name: str) -> str:
    m = re.search(rf'\(property "{re.escape(name)}" "([^"]*)"', block)
    return m.group(1).strip() if m else ""

def _set_prop(block: str, name: str, new_value: str) -> str:
    pattern = rf'(\(property "{re.escape(name)}" )"([^"]*)"'
    if re.search(pattern, block):
        return re.sub(pattern, rf'\1"{new_value}"', block, count=1)
    return block

def parse_all_symbols(content: str) -> list[dict]:
    results = []
    for m in re.finditer(r'\n\t\(symbol "([^"]+)"\s*\n\t\t\(exclude_from_sim', content):
        name = m.group(1)
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

def cmd_import(lcsc_id: str):
    """Import a part from LCSC via easyeda2kicad and add it to R_Library."""
    import tempfile

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

    # Run easyeda2kicad into a temp directory, then merge
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sym_out  = tmp / "imported.kicad_sym"
        fp_out   = tmp / "imported.pretty"
        m3d_out  = tmp / "imported.3dshapes"
        fp_out.mkdir();  m3d_out.mkdir()

        run_args = cmd + [
            '--lcsc_id',    lcsc_id,
            '--output',     str(sym_out),
            '--footprint',  str(fp_out),
            '--3d_models',  str(m3d_out),
        ]
        result = subprocess.run(run_args, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"easyeda2kicad failed:\n{result.stderr}")
            return

        # Parse imported symbols
        if not sym_out.exists():
            print("No symbol file was generated.")
            return

        imp_content = sym_out.read_text(encoding='utf-8')
        imp_symbols = parse_all_symbols(imp_content)
        if not imp_symbols:
            print("No symbols found in imported file.")
            return

        # Assign PNs and update values
        from build_library import (
            alloc_pn, VALUE_BUILDERS, _set_prop
        )

        new_blocks = []
        for s in imp_symbols:
            pn = alloc_pn(reg, s['name'], s['ref'])
            builder = VALUE_BUILDERS.get(s['ref'], VALUE_BUILDERS.get('MISC', lambda n,d,p: f"{n} | {p}"))
            new_val = builder(s['name'], s['description'], pn)
            new_fp  = s['footprint'].replace('easyeda2kicad:', 'R_Library:')

            blk = _set_prop(s['block'], 'Value', new_val)
            blk = _set_prop(blk, 'Footprint', new_fp)

            # Add Part Number property before the first sub-symbol definition
            if '"Part Number"' not in blk:
                sub_sym = re.search(r'\n\t\t\(symbol "', blk)
                if sub_sym:
                    ip = sub_sym.start() + 1
                    pn_prop = (
                        f'\t\t(property "Part Number" "{pn}"\n'
                        f'\t\t\t(at 0 -15.24 0)\n\t\t\t(show_name no)\n'
                        f'\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n'
                        f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
                        f'\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                    )
                    blk = blk[:ip] + pn_prop + blk[ip:]

            new_blocks.append(blk)
            print(f"  {s['name']} -> {pn} | {new_val[:60]}")

        # Merge into R_Library.kicad_sym
        content = SYM_FILE.read_text(encoding='utf-8')
        if content.rstrip().endswith(')'):
            content = content.rstrip()[:-1].rstrip() + '\n'
        content += '\n' + '\n'.join(new_blocks) + '\n)\n'
        SYM_FILE.write_text(content, encoding='utf-8')

        # Copy footprints
        for fp_file in fp_out.rglob('*.kicad_mod'):
            dst = ROOT / 'R_Library.pretty' / fp_file.name
            # Fix 3D model path in footprint
            fp_text = fp_file.read_text(encoding='utf-8')
            fp_text = fp_text.replace('easyeda2kicad.3dshapes', 'R_Library.3dshapes')
            dst.write_text(fp_text, encoding='utf-8')
            print(f"  Footprint: {fp_file.name}")

        # Copy 3D models
        for m3d_file in m3d_out.iterdir():
            dst = ROOT / 'R_Library.3dshapes' / m3d_file.name
            shutil.copy2(str(m3d_file), str(dst))
            print(f"  3D model: {m3d_file.name}")

        save_registry(reg)
        print(f"\nSuccessfully imported {lcsc_id} into R_Library.")

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
