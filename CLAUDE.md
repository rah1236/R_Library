# R_Library — KiCad Parts Library

Personal KiCad parts library seeded from `easyeda2kicad`. All parts have been
assigned internal part numbers and enriched value fields.

---

## Part Numbering Scheme

**Format:** `r#######-##-A`

| Field | Width | Meaning |
|---|---|---|
| `r` | prefix | Library identifier (Raheel's library) |
| `#######` | 7 digits | Part number (category-encoded, sequential) |
| `##` | 2 digits | Variant: `01` = primary; `02+` = alternate manufacturer source |
| `A` | 1 char | Version: always `A` for discrete parts; `A/B/C/...` for board assemblies |

### Category Ranges

| Range | Category |
|---|---|
| `r1000001–r1999999` | Resistors |
| `r2000001–r2999999` | Capacitors |
| `r3000001–r3999999` | Inductors & Magnetic / Ferrite Beads |
| `r4000001–r4999999` | Diodes, Rectifiers, TVS & ESD Protection |
| `r5000001–r5999999` | LEDs & Optoelectronics |
| `r6000001–r6999999` | Transistors & MOSFETs |
| `r7000001–r7999999` | Integrated Circuits |
| `r8000001–r8999999` | Connectors (J=r80, CN=r81, USB=r82, Card=r83) |
| `r9000001–r9499999` | Crystals, Oscillators, Switches & Misc |
| `r9500001–r9999999` | PCB Assemblies & Full Boards (version field active) |

### Variant Field (`##`)

`-01` is the primary/only manufacturer source for that part.
`-02`, `-03`, ... are used when importing the same part from a different
manufacturer (same value/function, different MPN). Variant does **not**
distinguish package size — different packages get different base part numbers.

### Version Field (`A`)

- **Discrete parts** (R, C, L, D, LED, Q, U, J, X, SW): version is always `A`.
  It does not change with minor footprint revisions.
- **Board assemblies** (`r9500001+`): `A` = first release, `B` = hardware rev B, etc.
  Increment the version letter when the board schematic or layout changes in a way
  that requires re-qualification.

---

## Value Field Conventions

Full symbol/field requirements live in [SPEC.md](SPEC.md). Summary:

The `Value` property (visible on schematic) is kept short. The internal part
number is **never** part of the Value — it lives in the dedicated
`Part Number` property, which is visible on the schematic just below Value.

| Category | Value format | Example |
|---|---|---|
| Resistor | `<pkg> <resistance> <tol> <power>` | `0402 10kΩ 1% 1/16W` |
| Capacitor (MLCC) | `<pkg> <cap> <voltage> <dielectric> <tol>` | `0603 2.2µF 25V X5R 10%` |
| Capacitor (bulk/electrolytic) | `<cap> <voltage> <type> <tol>` | `220µF 63V Al-elec 20%` |
| Thermistor | `<pkg> NTC <R> <B-constant>` | `0603 NTC 10kΩ B3950` |
| Everything else (IC, Q, D, LED, L, X, connector, SW, fuse…) | `<MPN>` | `STM32H723ZGT6` |

If a passive's spec can't be decoded reliably, its Value falls back to the MPN.
The human-readable spec always goes in the `Description` property
(e.g. `Resistor 0402 10kΩ 1% 1/16W`, `MCU ARM Cortex-M7 550MHz 1MB flash ETH LQFP-144`).

---

## Directory Structure

```
R_Library/
├── R_Library.kicad_sym      # Symbol library (add to KiCad global libraries)
├── R_Library.pretty/        # Footprint library
├── R_Library.3dshapes/      # 3D models (.step + .wrl)
├── pn_registry.json         # Part number registry — tracks all assigned PNs
├── SPEC.md                  # Authoritative library specification
├── CLAUDE.md                # This file
└── tools/
    ├── library_manager.py   # Main CLI tool (search, import, add-board)
    ├── build_library.py     # Converts easyeda2kicad source → R_Library
    └── pn_scheme.py         # Part number category constants & helpers
```

---

## Registering Libraries in KiCad

Open KiCad → Preferences → Manage Symbol Libraries → Global Libraries tab:

| Nickname | Library Path |
|---|---|
| `R_Library` | `C:\Users\raheel\Documents\KiCad\R_Library\R_Library.kicad_sym` |

Open KiCad → Preferences → Manage Footprint Libraries → Global Libraries tab:

| Nickname | Library Path |
|---|---|
| `R_Library` | `C:\Users\raheel\Documents\KiCad\R_Library\R_Library.pretty` |

---

## Workflow: Adding New Parts

### From LCSC (via easyeda2kicad)

```bash
cd C:\Users\raheel\Documents\KiCad\R_Library\tools

# Import by LCSC part number
python library_manager.py import C2977777

# Verify it was added
python library_manager.py info C2977777
```

This will:
1. Call `easyeda2kicad` to download symbol, footprint, and 3D model
2. Automatically assign the next available PN from the correct category
3. Build the enriched Value field
4. Merge the symbol into `R_Library.kicad_sym`
5. Copy footprint and 3D model into the library folders

### Manually (for custom parts)

Edit `R_Library.kicad_sym` directly in the KiCad Symbol Editor, then
add the part to `pn_registry.json` manually, following the same conventions.

---

## Workflow: Registering a New PCB Assembly

```bash
python library_manager.py add-board "IrisSensorBoard" "Rev A sensor mainboard for Iris project"
# -> r9500001-01-A

# When rev B is taped out, manually update the board record to:
# r9500001-01-B
```

Board PNs live in the `r9500001+` range. The version letter (A/B/C) is the
hardware revision. Update it in `pn_registry.json` when the board is revised.

---

## Workflow: Searching

```bash
# Find all 10k resistors
python library_manager.py search 10k

# Find by part number
python library_manager.py search r2000001

# List all capacitors
python library_manager.py list C

# Full part details
python library_manager.py info LSM6DSOTR
```

---

## Rebuilding from Source

If you re-run `easyeda2kicad` on the source library and want to regenerate
`R_Library.kicad_sym` while preserving existing part numbers:

```bash
python library_manager.py rebuild
# or directly:
python build_library.py
```

Part numbers are preserved because `build_library.py` checks `pn_registry.json`
before allocating new numbers — existing parts always get their original PN back.

---

## Source Library

Parts were originally imported from EasyEDA/LCSC into:
`C:\Users\raheel\Documents\KiCad\easyeda2kicad\easyeda2kicad.kicad_sym`

The `tools/build_library.py` script reads from that path. When you use
`easyeda2kicad` to add new parts to the source library, run `rebuild` to
pick up any new symbols that were added.
