import sys, re
sys.path.insert(0, r'C:\Users\raheel\Documents\KiCad\R_Library\tools')
from library_manager import load_library

_, syms = load_library()
targets = ['RP2354B_C39843328', 'AE5002']

pin_name_re = re.compile(r'\(name\s+"([^"]+)"')
pin_num_re  = re.compile(r'\(number\s+"([^"]+)"')

for s in syms:
    if s['name'] in targets:
        print(f'\n=== {s["name"]} ({s["part_number"]}) ===')
        block = s['block']
        i, pins = 0, []
        while True:
            pm = re.search(r'\(pin ', block[i:])
            if not pm:
                break
            ps = i + pm.start()
            depth, j, in_str = 0, ps, False
            while j < len(block):
                c = block[j]
                if c == '"' and (j == 0 or block[j-1] != '\\'):
                    in_str = not in_str
                if not in_str:
                    if c == '(':   depth += 1
                    elif c == ')':
                        depth -= 1
                        if depth == 0:
                            pblock = block[ps:j+1]
                            nm = pin_name_re.search(pblock)
                            nu = pin_num_re.search(pblock)
                            if nm and nu:
                                pins.append((nu.group(1), nm.group(1)))
                            break
                j += 1
            i = ps + 1
        def sort_key(t):
            try: return int(t[0])
            except: return 9999
        for num, name in sorted(pins, key=sort_key):
            print(f'  pin {num:4}: {name}')
