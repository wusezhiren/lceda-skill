// 位号丝印自动整理：统一字号/居中，逐个在器件四周找不压焊盘、不压别的器件、不出板、不互压的位置；找不到就隐藏
// （高密度 0201 板常见做法：放不下的位号隐藏，靠装配图/BOM 定位）。
// 用法：python3 scripts/lceda.py run scripts/pcb_silk.js --args '{"size":0.6}' --timeout 200
// 参数：size 字高 mm（默认 0.6；0201 板可 0.5），line 线宽（默认 0.1），hide:[强制隐藏的位号]，order:[优先摆放的位号]
await openPcb();
const A = (typeof ARGS === 'object' && ARGS) || {};
const SIZE = A.size || 0.6, LW = A.line || 0.1, GAP = A.gap ?? 0.08;
const box = (x, y, w, h, rot) => { const t = (rot || 0) * Math.PI / 180, c = Math.abs(Math.cos(t)), s = Math.abs(Math.sin(t));
	const hw = c * w / 2 + s * h / 2, hh = s * w / 2 + c * h / 2; return [x - hw, y - hh, x + hw, y + hh]; };
const ov = (a, b, g = 0) => a[0] < b[2] + g && b[0] < a[2] + g && a[1] < b[3] + g && b[1] < a[3] + g;
const ol = await eda.pcb_PrimitivePolyline.getAll(undefined, EPCB_LayerId.BOARD_OUTLINE);
const bb = await eda.pcb_Primitive.getPrimitivesBBox(ol.map(l => l.getState_PrimitiveId()));
const BD = [bb.minX / MM + 0.2, bb.minY / MM + 0.2, bb.maxX / MM - 0.2, bb.maxY / MM - 0.2];
const comps = [];
const padObs = { 1: [], 2: [] };            // 各面焊盘（通孔焊盘两面都算）
const envObs = { 1: [], 2: [] };            // 各面器件焊盘包络（视作器件本体）
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
	const id = c.getState_PrimitiveId(), side = c.getState_Layer() === EPCB_LayerId.BOTTOM ? 2 : 1;
	const bs = [];
	for (const p of (await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id)) || []) {
		const sh = p.getState_Pad(); const b = box(p.getState_X() / MM, p.getState_Y() / MM, (sh?.[1] || 0) / MM, (sh?.[2] || 0) / MM, p.getState_Rotation());
		bs.push(b);
		if (p.getState_Layer() === EPCB_LayerId.MULTI) { padObs[1].push(b); padObs[2].push(b); } else padObs[side].push(b);
	}
	if (!bs.length) continue;
	const env = [Math.min(...bs.map(b => b[0])), Math.min(...bs.map(b => b[1])), Math.max(...bs.map(b => b[2])), Math.max(...bs.map(b => b[3]))];
	envObs[side].push([env, c.getState_Designator()]);
	comps.push({ id, ref: c.getState_Designator(), side, env, area: (env[2] - env[0]) * (env[3] - env[1]) });
}
for (const p of await freePads()) {
	const sh = p.getState_Pad(); const b = box(p.getState_X() / MM, p.getState_Y() / MM, (sh?.[1] || 0) / MM, (sh?.[2] || 0) / MM, 0);
	if (p.getState_Layer() !== EPCB_LayerId.BOTTOM) padObs[1].push(b);
	if (p.getState_Layer() !== EPCB_LayerId.TOP) padObs[2].push(b);
}
for (const v of await eda.pcb_PrimitiveVia.getAll()) { const r = v.getState_Diameter() / MM / 2, x = v.getState_X() / MM, y = v.getState_Y() / MM; padObs[1].push([x - r, y - r, x + r, y + r]); padObs[2].push([x - r, y - r, x + r, y + r]); }
const placed = { 1: [], 2: [] };
const order = A.order || [];
comps.sort((a, b) => (order.includes(b.ref) - order.includes(a.ref)) || (b.area - a.area));   // 大件先摆，小件挤剩下的位置
const res = { shown: 0, hidden: [] };
for (const c of comps) {
	const attr = (await eda.pcb_PrimitiveAttribute.getAll(c.id)).find(a => a.getState_Key() === 'Designator');
	if (!attr) continue;
	const w = 0.62 * SIZE * c.ref.length + 0.1, h = SIZE + 0.1;
	const [x0, y0, x1, y1] = c.env, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
	let best = null;
	if (!(A.hide || []).includes(c.ref)) {
		for (let k = 0; k <= 8 && !best; k++) {
			const d = GAP + k * 0.12;
			for (const [px, py] of [[cx, y1 + d + h / 2], [cx, y0 - d - h / 2], [x1 + d + w / 2, cy], [x0 - d - w / 2, cy],
				[x1 + d + w / 2, y1 + d + h / 2], [x0 - d - w / 2, y1 + d + h / 2], [x1 + d + w / 2, y0 - d - h / 2], [x0 - d - w / 2, y0 - d - h / 2]]) {
				const b = [px - w / 2, py - h / 2, px + w / 2, py + h / 2];
				if (b[0] < BD[0] || b[1] < BD[1] || b[2] > BD[2] || b[3] > BD[3]) continue;
				if (padObs[c.side].some(o => ov(b, o, 0.05))) continue;
				if (envObs[c.side].some(([o, r]) => ov(b, o, 0.02))) continue;
				if (placed[c.side].some(o => ov(b, o, 0.05))) continue;
				best = [px, py, b]; break;
			}
		}
	}
	const layer = c.side === 2 ? EPCB_LayerId.BOTTOM_SILKSCREEN : EPCB_LayerId.TOP_SILKSCREEN;
	if (best) {
		await eda.pcb_PrimitiveAttribute.modify(attr.getState_PrimitiveId(), { x: mm(best[0]), y: mm(best[1]), fontSize: mm(SIZE), lineWidth: mm(LW),
			alignMode: EPCB_PrimitiveStringAlignMode.CENTER, rotation: 0, valueVisible: true, keyVisible: false, layer });
		placed[c.side].push(best[2]); res.shown++;
	} else {
		await eda.pcb_PrimitiveAttribute.modify(attr.getState_PrimitiveId(), { valueVisible: false, keyVisible: false });
		res.hidden.push(c.ref);
	}
}
return res;
