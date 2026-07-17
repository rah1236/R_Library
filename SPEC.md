# R_Library Specification

Authoritative specification for parts in `R_Library`. When this document and
any other file disagree, this document wins. Quick-reference summaries live in
`CLAUDE.md`; the numbering constants are implemented in `tools/pn_scheme.py`.

---

## 1. Part Numbering

**Format:** `r#######-##-V`

| Field | Width | Meaning |
|---|---|---|
| `r` | prefix | Library identifier |
| `#######` | 7 digits | Base part number (category-encoded, sequential) |
| `##` | 2 digits | Variant: `01` = primary; `02+` = alternate manufacturer source (same value/function, different MPN). Never used for package differences — a different package is a different base PN |
| `V` | 1 letter | Version: always `A` for discrete parts; `A/B/C…` = hardware revision for board assemblies |

### Category ranges

| Range | Category | Reference |
|---|---|---|
| `r1000001–r1999999` | Resistors (incl. shunts, NTC/PTC) | R |
| `r2000001–r2999999` | Capacitors | C |
| `r3000001–r3999999` | Inductors, ferrite beads, common-mode chokes | L |
| `r4000001–r4999999` | Diodes, rectifiers, TVS, ESD protection | D |
| `r5000001–r5999999` | LEDs & optoelectronics | LED |
| `r6000001–r6999999` | Transistors & MOSFETs | Q |
| `r7000001–r7999999` | Integrated circuits | U |
| `r8000001–r8099999` | Connectors (J) | J |
| `r8100001–r8199999` | Connectors (CN) | CN |
| `r8200001–r8299999` | USB connectors | USB |
| `r8300001–r8399999` | Card connectors | Card |
| `r9000001–r9099999` | Switches | SW |
| `r9100001–r9199999` | Crystals & oscillators | X |
| `r9200001–r9499999` | Miscellaneous (fuse holders, hardware…) | misc (FH, F, …) |
| `r9500001–r9999999` | PCB assemblies & boards (version field active) | — |

A part must be numbered in the range matching its reference designator. If an
import lands in the wrong category (easyeda2kicad sometimes assigns `U` to
connectors, diodes, etc.), fix the reference **and** re-allocate the PN into
the correct range before committing.

## 2. Symbol file format

- Single library file `R_Library.kicad_sym`, KiCad 10 s-expression format,
  tab indentation. After hand edits or script edits, normalize with:
  `kicad-cli sym upgrade --force R_Library.kicad_sym`
- No legacy easyeda2kicad blocks (2-space indent, `(id N)` fields) may remain.
- `pn_registry.json` is UTF-8 **without BOM**; keys are symbol names.

## 3. Required symbol properties

| Property | Content | Visibility |
|---|---|---|
| `Reference` | Category designator (R, C, L, D, LED, Q, U, J, CN, USB, Card, SW, X, FH…) | visible |
| `Value` | See §4 | visible |
| `Part Number` | Internal PN `r#######-##-V` | **visible**, placed 2.54 mm below `Value` |
| `Footprint` | `R_Library:<footprint name>` | hidden |
| `Datasheet` | Manufacturer datasheet URL, or LCSC product page `https://www.lcsc.com/product-detail/<Cxxxx>.html` | hidden |
| `Description` | Human-readable spec (see §5) | hidden |
| `LCSC Part` | LCSC code `Cxxxxx` (when sourced via LCSC) | hidden |

## 4. Value field

The Value is what appears next to the part on a schematic — keep it short and
useful. **The internal part number is never part of the Value** (it has its
own visible field).

| Category | Value format | Example |
|---|---|---|
| Resistor | `<pkg> <resistance> <tol> <power>` | `0402 10kΩ 1% 1/16W` |
| Shunt | `<pkg> <resistance> <tol> <power>` | `2512 2mΩ 1% 3W` |
| Thermistor | `<pkg> NTC <R> <B-constant>` | `0603 NTC 10kΩ B3950` |
| Capacitor (MLCC) | `<pkg> <cap> <voltage> <dielectric> <tol>` | `0603 2.2µF 25V X5R 10%` |
| Capacitor (bulk) | `<cap> <voltage> <type> <tol>` | `220µF 63V Al-elec 20%` |
| All MPN-designated parts (IC, transistor, diode, LED, inductor, crystal, connector, switch, fuse holder…) | `<MPN>` | `STM32H723ZGT6` |

- 0 Ω resistors omit tolerance: `0402 0Ω 1/16W`.
- If a passive's spec can't be decoded confidently, fall back to `<MPN>`
  rather than guessing.

## 5. Description field

Human-readable spec, redundant with nothing on the schematic:

- Passives: `<Category> <Value string>` — e.g. `Resistor 0603 4.7Ω 1% 1/10W`,
  `Capacitor 1210 47µF 25V X5R 20%`, `NTC thermistor 0603 NTC 10kΩ B3950`.
- ICs: function + key specs + package — e.g.
  `MCU ARM Cortex-M7 550MHz 1MB flash ETH LQFP-144`,
  `100BASE-T1 automotive Ethernet PHY RMII QFN-36`.
- Others: short type/spec summary — e.g. `TVS 48V standoff 3000W unidirectional SMC`,
  `Connector JST-GH 1.25mm 6P SMD right-angle`.

## 6. Symbol quality

- Pin names follow the manufacturer datasheet exactly (including bus indices —
  `TXD[3]`, not `TXD`). Verify against the datasheet when importing; EasyEDA
  symbols frequently drop indices or contain typos.
- Electrical pin types set where known: supplies `power_in`, grounds
  `power_in`, plain caps pins `passive`, straps/config `input`, GPIO
  `bidirectional`.
- **Multi-unit symbols:** ICs with more than ~48 pins should be split into
  units — one power/system unit (supplies top, grounds bottom, reset/boot/osc
  on the sides) plus functional/port units. Give each unit a `unit_name`
  (e.g. "Power/System", "Port A"). Keep unit bodies wide enough that left and
  right pin names cannot collide.
- Symbol name = clean MPN (strip easyeda suffixes like `_C123456` or
  truncated `(N` fragments) — the LCSC code lives in `LCSC Part`.

## 7. Footprints & 3D models

- Footprints live in `R_Library.pretty/`, referenced as `R_Library:<name>`.
- 3D model paths point into `R_Library.3dshapes/`.
- Never overwrite an existing curated footprint when importing a new part
  that reuses a shared package (R0603, C0805…) — keep the curated version.

## 8. Workflows

### Import (LCSC)

```bash
python tools/library_manager.py import Cxxxxx
```

Post-import checklist (the importer does not do all of this yet):
1. Reference/category correct → PN in the right range (§1).
2. Symbol name is the clean MPN (§6).
3. Value per §4, Description per §5.
4. `Part Number` visible below Value; `Datasheet` filled (§3).
5. Pin names spot-checked against the datasheet (§6).
6. `kicad-cli sym upgrade --force R_Library.kicad_sym` to normalize format.
7. Validate (§9).

Space bulk imports ≥20 s apart — the EasyEDA API rate-limits and starts
returning 403 after ~10–15 rapid requests.

### Boards

```bash
python tools/library_manager.py add-board "Name" "Description"
```

Board PNs live at `r9500001+`; bump the version letter in `pn_registry.json`
on each hardware revision.

## 9. Validation

After any batch of changes:

```bash
kicad-cli sym upgrade --force R_Library.kicad_sym   # format normalize
kicad-cli sym export svg -o <tmp> R_Library.kicad_sym  # full parse/render check
```

and check: no `(id ` tokens or 2-space symbol blocks remain; every symbol has
a visible `Part Number` matching `pn_registry.json` (no duplicates); every
`Footprint` reference resolves to a file in `R_Library.pretty/`; no Value
contains ` | r`.
