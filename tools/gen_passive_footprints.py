"""
gen_passive_footprints.py
Generates IPC-7351B nominal (Level B) SMT footprints for R and C chip packages.

Dimensions used are IPC-7351B nominal for:
  0402, 0603, 0805, 1206, 2512

Each footprint includes:
  F.Cu / F.Mask / F.Paste  — pads
  F.Fab                    — body outline + pin-1 dot
  F.CrtYd                  — courtyard (0.25mm clearance from outer pad edge)
  F.SilkS                  — body reference lines (clear of pads)
  Reference text on F.SilkS, Value text on F.Fab
"""

from pathlib import Path
import re

PRETTY = Path(__file__).parent.parent / "R_Library.pretty"

# ── Package data (IPC-7351B nominal) ─────────────────────────────────────────
# Each entry: (body_L, body_W, pad_X, pad_Y, center_x)
#   body_L / body_W : physical component body dimensions
#   pad_X           : pad length (in X, solder-direction)
#   pad_Y           : pad width  (in Y)
#   center_x        : pad center offset from origin (pads at ±center_x)

PACKAGES = {
    #        body_L  body_W  pad_X  pad_Y  center_x
    '0402': ( 1.00,   0.50,  0.56,  0.62,   0.48 ),
    '0603': ( 1.60,   0.80,  0.90,  0.95,   0.97 ),
    '0805': ( 2.00,   1.25,  1.00,  1.45,   1.30 ),
    '1206': ( 3.20,   1.60,  1.50,  1.90,   2.00 ),
    '2512': ( 6.30,   3.20,  2.00,  3.50,   3.05 ),
}

# Reference designators to generate footprints for
REF_TYPES = {
    'R': 'Resistor',
    'C': 'Capacitor',
}

# ── helpers ───────────────────────────────────────────────────────────────────

def f(v):
    """Format a float to 4dp, stripping trailing zeros."""
    return f"{v:.4f}".rstrip('0').rstrip('.')

def extract_3d_model(fp_name: str) -> str | None:
    """Read existing footprint and return its (model ...) block, or None."""
    existing = PRETTY / f"{fp_name}.kicad_mod"
    if not existing.exists():
        return None
    txt = existing.read_text(encoding='utf-8')
    m = re.search(r'\n\t(\(model "[^"]*".*?\))\n\)', txt, re.DOTALL)
    if m:
        return '\t' + m.group(1)
    # Try simpler search
    m2 = re.search(r'(\(model "[^"]*"(?:(?!\)\n\)).)*\))', txt, re.DOTALL)
    return m2.group(1) if m2 else None

def make_line(x1, y1, x2, y2, layer, width=0.12):
    return (f'\t(fp_line (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)})\n'
            f'\t\t(stroke (width {f(width)}) (type default)) (layer "{layer}"))\n')

def make_rect(x1, y1, x2, y2, layer, width=0.12):
    """Four lines forming a closed rectangle."""
    lines = ""
    lines += make_line(x1, y1, x2, y1, layer, width)
    lines += make_line(x2, y1, x2, y2, layer, width)
    lines += make_line(x2, y2, x1, y2, layer, width)
    lines += make_line(x1, y2, x1, y1, layer, width)
    return lines

def make_text(text, x, y, layer, size=1.0, mirror=False, hide=False):
    hide_str = '\n\t\t(hide yes)' if hide else ''
    mirror_str = '\n\t\t(justify mirror)' if mirror else ''
    return (f'\t(fp_text "{text}" (at {f(x)} {f(y)} 0)\n'
            f'\t\t(layer "{layer}"){hide_str}\n'
            f'\t\t(effects (font (size {f(size)} {f(size)}) (thickness {f(size*0.15)})){mirror_str})\n'
            f'\t)\n')

def make_prop(name, value, x, y, layer, size=1.0, hide=False):
    hide_str = '\n\t\t(hide yes)' if hide else ''
    return (f'\t(property "{name}" "{value}"\n'
            f'\t\t(at {f(x)} {f(y)} 0)\n'
            f'\t\t(layer "{layer}"){hide_str}\n'
            f'\t\t(effects\n'
            f'\t\t\t(font (size {f(size)} {f(size)}) (thickness {f(size*0.15)}))\n'
            f'\t\t)\n'
            f'\t)\n')

def make_pad(num, x, y, w, h, shape='rect'):
    return (f'\t(pad "{num}" smd {shape}\n'
            f'\t\t(at {f(x)} {f(y)} 0)\n'
            f'\t\t(size {f(w)} {f(h)})\n'
            f'\t\t(layers "F.Cu" "F.Mask" "F.Paste")\n'
            f'\t)\n')

def make_circle(cx, cy, r, layer, width=0.12):
    return (f'\t(fp_circle (center {f(cx)} {f(cy)}) (end {f(cx+r)} {f(cy)})\n'
            f'\t\t(stroke (width {f(width)}) (type default)) (fill solid) (layer "{layer}"))\n')

# ── footprint builder ─────────────────────────────────────────────────────────

def build_footprint(ref: str, pkg: str) -> str:
    body_L, body_W, pad_X, pad_Y, cx = PACKAGES[pkg]
    fp_name = f"{ref}{pkg}"
    desc = f"IPC-7351B nominal, {REF_TYPES[ref]} {pkg}"

    # Derived geometry
    crtyd_x = cx + pad_X/2 + 0.25
    crtyd_y = pad_Y/2 + 0.25
    fab_x   = body_L / 2
    fab_y   = body_W / 2

    # Silkscreen: short lines between pads, at Y = ±(body_W/2 + 0.12)
    # clearance from inner pad edge = 0.07mm
    silk_y    = fab_y + 0.12
    silk_x    = cx - pad_X/2 - 0.07   # inner pad edge - 0.07mm clearance

    # Text sizing: scale with package (0402 smallest, 2512 largest)
    txt_size = max(0.6, min(1.0, body_L * 0.35))

    # Reference text sits above courtyard, Value on Fab
    ref_y = -(crtyd_y + txt_size * 0.6)
    val_y =  fab_y + txt_size * 0.6

    lines = []
    lines.append(f'(footprint "{fp_name}"\n')
    lines.append(f'\t(version 20241229)\n')
    lines.append(f'\t(generator "R_Library_scripts")\n')
    lines.append(f'\t(generator_version "1.0")\n')
    lines.append(f'\t(layer "F.Cu")\n')
    lines.append(f'\t(attr smd)\n')

    # Properties
    lines.append(make_prop("Reference",   "REF**", 0, ref_y, "F.SilkS", size=txt_size))
    lines.append(make_prop("Value",       fp_name, 0, val_y, "F.Fab",  size=txt_size, hide=True))
    lines.append(make_prop("Description", desc,    0, 0,     "F.Fab",  size=txt_size, hide=True))

    # F.Fab — component body outline
    lines.append(make_rect(-fab_x, -fab_y, fab_x, fab_y, "F.Fab", 0.10))

    # Pin-1 dot on F.Fab (bottom-left of body, inside)
    lines.append(make_circle(-fab_x + fab_x*0.35, -fab_y + fab_y*0.45, 0.06, "F.Fab", 0.06))



    # F.SilkS — two short horizontal lines between pads (top and bottom)
    if silk_x > 0.05:
        lines.append(make_line(-silk_x, -silk_y,  silk_x, -silk_y, "F.SilkS", 0.12))
        lines.append(make_line(-silk_x,  silk_y,  silk_x,  silk_y, "F.SilkS", 0.12))

    # Pads
    lines.append(make_pad("1", -cx, 0, pad_X, pad_Y))
    lines.append(make_pad("2",  cx, 0, pad_X, pad_Y))

    # 3D model — preserve from existing file
    model_block = extract_3d_model(fp_name)
    if model_block:
        lines.append(f'{model_block}\n')
    else:
        print(f"  [!] No 3D model found for {fp_name}")

    lines.append(')\n')
    return ''.join(lines)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    generated = []
    for ref in ('R', 'C'):
        for pkg in ('0402', '0603', '0805', '1206'):
            fp_name = f"{ref}{pkg}"
            if pkg == '0402' and ref == 'C':
                pass  # C0402 uses same dims as R0402

            content = build_footprint(ref, pkg)
            out_path = PRETTY / f"{fp_name}.kicad_mod"
            out_path.write_bytes(content.encode('utf-8'))
            generated.append(fp_name)
            print(f"  Written {fp_name}.kicad_mod")

    # R2512 (resistor only — no C2512 in library)
    content = build_footprint('R', '2512')
    (PRETTY / "R2512.kicad_mod").write_bytes(content.encode('utf-8'))
    generated.append('R2512')
    print(f"  Written R2512.kicad_mod")

    print(f"\nGenerated {len(generated)} footprints:")
    print(f"  " + ", ".join(generated))
    print("\nIPC-7351B nominal (Level B) pad dimensions:")
    print(f"  {'Pkg':<6}  {'PadX':>6}  {'PadY':>6}  {'Center':>8}  {'CrtYd±X':>9}  {'CrtYd±Y':>9}")
    for pkg, (bL, bW, pX, pY, cx) in PACKAGES.items():
        if pkg == '2512' and 'R' not in generated:
            continue
        cX = cx + pX/2 + 0.25
        cY = pY/2 + 0.25
        print(f"  {pkg:<6}  {pX:>6.2f}  {pY:>6.2f}  {'±'+str(round(cx,3)):>8}  {'±'+str(round(cX,3)):>9}  {'±'+str(round(cY,3)):>9}")

if __name__ == '__main__':
    main()
