#!/usr/bin/env python3
"""把 pcb_dump.js 导出的 PCB 数据画成 PNG 供目视检查。

用法：pcb_render.py dump.json out.png [top|bottom|all] [像素/mm，默认 40]
红=顶层铜/焊盘，蓝=底层，灰=通孔焊盘，白点=过孔，黄框=顶层器件外形，青框=底层器件，绿字=可见位号丝印。
"""
import json, sys, math
from PIL import Image, ImageDraw, ImageFont
d = json.load(open(sys.argv[1])); out = sys.argv[2]; side = sys.argv[3] if len(sys.argv) > 3 else 'all'
B = d.get('board') or [0, 0, 20, 28]
W, H = B[2] - B[0], B[3] - B[1]
S = int(sys.argv[4]) if len(sys.argv) > 4 else 40; M = 30
im = Image.new('RGB', (int(W * S + 2 * M), int(H * S + 2 * M)), (20, 20, 28)); g = ImageDraw.Draw(im, 'RGBA')
try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
except Exception: font = ImageFont.load_default()
X = lambda x: M + (x - B[0]) * S; Y = lambda y: M + (B[3] - y) * S
g.rectangle([X(B[0]), Y(B[3]), X(B[2]), Y(B[1])], outline=(255, 0, 255), width=2)
for y in range(int(B[1]), int(B[3]) + 1, 5): g.line([X(B[0]), Y(y), X(B[2]), Y(y)], fill=(60, 60, 70))
for x in range(int(B[0]), int(B[2]) + 1, 5): g.line([X(x), Y(B[1]), X(x), Y(B[3])], fill=(60, 60, 70))
LCOL = {1: (230, 60, 60, 170), 2: (60, 120, 255, 150), 15: (230, 180, 40, 90), 16: (60, 200, 120, 90)}
def poly_src(src):
    pts, i = [], 0
    src = [v for v in src if v not in ('L',)]
    while i + 1 < len(src):
        if isinstance(src[i], (int, float)) and isinstance(src[i + 1], (int, float)): pts.append((src[i] / 39.3700787, src[i + 1] / 39.3700787)); i += 2
        else: i += 1
    return pts
for layer, net, src in d.get('fills', []):
    if not src: continue
    for ring in (src if isinstance(src[0], list) else [src]):
        p = poly_src(ring)
        if len(p) > 2: g.polygon([(X(a), Y(b)) for a, b in p], fill=LCOL.get(layer, (200, 200, 200, 120)))
for layer, net, x1, y1, x2, y2, w in d.get('lines', []):
    if side == 'top' and layer != 1 or side == 'bottom' and layer != 2: continue
    g.line([X(x1), Y(y1), X(x2), Y(y2)], fill=LCOL.get(layer, (200, 200, 200, 160)), width=max(1, int(w * S)))
def pad(x, y, shape, w, h, rot, layer, net):
    if side == 'top' and layer == 2 or side == 'bottom' and layer == 1: return
    c = {1: (220, 50, 50, 230), 2: (50, 110, 250, 230), 12: (200, 200, 200, 230)}.get(layer, (200, 200, 50, 230))
    a = math.radians(rot or 0); ca, sa = math.cos(a), math.sin(a)
    pts = [(x + ca * u - sa * v, y + sa * u + ca * v) for u, v in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]]
    if shape in ('ELLIPSE', 'OVAL'): g.ellipse([X(x - w / 2), Y(y + h / 2), X(x + w / 2), Y(y - h / 2)], fill=c)
    else: g.polygon([(X(p), Y(q)) for p, q in pts], fill=c)
for ref, c in d['comps'].items():
    lay = c['layer']
    if side == 'top' and lay == 2 or side == 'bottom' and lay == 1: continue
    for p in c['pads']: pad(p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[1])
for ref, c in d['comps'].items():
    lay = c['layer']
    if side == 'top' and lay == 2 or side == 'bottom' and lay == 1: continue
    x0, y0, x1, y1 = c['bb']; col = (255, 255, 0) if lay == 1 else (120, 200, 255)
    g.rectangle([X(x0), Y(y1), X(x1), Y(y0)], outline=col)
    s = c.get('des')
    if s and s.get('visible'):
        fs = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', max(8, int(s['size'] * S * 0.95))) if hasattr(font, 'path') else font
        g.text((X(s['x']), Y(s['y'])), ref, fill=(80, 255, 120), font=fs, anchor='mm')
    else:
        g.text((X(c['x']), Y(c['y'])), ref, fill=(150, 150, 150), font=font, anchor='mm')
for p in d.get('free', []): pad(p[2], p[3], p[4], p[5], p[6], 0, p[7], p[1])
for net, x, y, dia in d.get('vias', []): g.ellipse([X(x - dia / 2), Y(y + dia / 2), X(x + dia / 2), Y(y - dia / 2)], fill=(240, 240, 240, 220))
im.save(out)
