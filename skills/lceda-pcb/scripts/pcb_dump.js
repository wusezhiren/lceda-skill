// 导出 PCB 几何供本地检查/渲染（单位 mm，Y 向上）。用法：
//   python3 scripts/lceda.py run scripts/pcb_dump.js --timeout 200 --json dump.json
//   python3 scripts/pcb_check.py dump.json ; python3 scripts/pcb_render.py dump.json out.png
// 焊盘：[号, 网络, x, y, 形状, w, h, rot, 层(1顶/2底/12通孔)(, 多边形mm点列)]；POLYGON 焊盘 w/h 取以焊盘中心为准的保守外包。
// pours：铺铜实际填充（getState_PourFills 原始数据，坐标单位 10mil），供 gnd_islands.py 做 GND 连通分析。
await openPcb();
const r3 = v => +(+v).toFixed(3);
const out = { board: null, comps: {}, free: [], fills: [], lines: [], vias: [], silk: [] };
const ol = await eda.pcb_PrimitivePolyline.getAll(undefined, EPCB_LayerId.BOARD_OUTLINE);
if (ol.length) {
	const bb = await eda.pcb_Primitive.getPrimitivesBBox(ol.map(l => l.getState_PrimitiveId()));
	out.board = [bb.minX, bb.minY, bb.maxX, bb.maxY].map(v => r3(v / MM));
}
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
	const id = c.getState_PrimitiveId();
	const bb = await eda.pcb_Primitive.getPrimitivesBBox([id]);
	const pads = [];
	for (const p of (await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id)) || []) {
		const sh = p.getState_Pad();
		const px = p.getState_X() / MM, py = p.getState_Y() / MM;
		const row = [p.getState_PadNumber(), p.getState_Net(), r3(px), r3(py),
			sh?.[0], r3((+sh?.[1] || 0) / MM), r3((+sh?.[2] || 0) / MM), p.getState_Rotation() ?? 0, p.getState_Layer()];
		if (sh?.[0] === 'POLYGON' && Array.isArray(sh[1])) {   // [x,y,'L',x,y,...] 绝对坐标 mil
			const pts = []; for (let i = 0; i < sh[1].length;) { if (typeof sh[1][i] === 'string') { i++; continue; } pts.push([r3(sh[1][i] / MM), r3(sh[1][i + 1] / MM)]); i += 2; }
			const ex = Math.max(...pts.map(q => Math.abs(q[0] - px))), ey = Math.max(...pts.map(q => Math.abs(q[1] - py)));
			row[5] = r3(2 * ex); row[6] = r3(2 * ey); row.push(pts);
		}
		pads.push(row);
	}
	const des = (await eda.pcb_PrimitiveAttribute.getAll(id)).find(a => a.getState_Key() === 'Designator');
	out.comps[c.getState_Designator()] = {
		x: r3(c.getState_X() / MM), y: r3(c.getState_Y() / MM), rot: c.getState_Rotation(), layer: c.getState_Layer(),
		bb: bb && [bb.minX, bb.minY, bb.maxX, bb.maxY].map(v => r3(v / MM)), pads,
		des: des && { x: r3(des.getState_X() / MM), y: r3(des.getState_Y() / MM), size: r3(des.getState_FontSize() / MM),
			visible: des.getState_ValueVisible(), rot: des.getState_Rotation(), layer: des.getState_Layer() },
	};
}
for (const p of await freePads()) {
	const sh = p.getState_Pad();
	out.free.push([p.getState_PadNumber(), p.getState_Net(), r3(p.getState_X() / MM), r3(p.getState_Y() / MM), sh?.[0], r3((sh?.[1] || 0) / MM), r3((sh?.[2] || 0) / MM), p.getState_Layer()]);
}
for (const f of await eda.pcb_PrimitiveFill.getAll()) out.fills.push([f.getState_Layer(), f.getState_Net(), f.getState_ComplexPolygon?.()?.getSource?.()]);
for (const l of await eda.pcb_PrimitiveLine.getAll())
	out.lines.push([l.getState_Layer(), l.getState_Net(), r3(l.getState_StartX() / MM), r3(l.getState_StartY() / MM), r3(l.getState_EndX() / MM), r3(l.getState_EndY() / MM), r3(l.getState_LineWidth() / MM)]);
for (const v of await eda.pcb_PrimitiveVia.getAll()) out.vias.push([v.getState_Net(), r3(v.getState_X() / MM), r3(v.getState_Y() / MM), r3(v.getState_Diameter() / MM)]);
out.pours = [];
const pourById = Object.fromEntries((await eda.pcb_PrimitivePour.getAll()).map(p => [p.getState_PrimitiveId(), p]));
for (const o of await eda.pcb_PrimitivePoured.getAll()) {
	const pp = pourById[o.getState_PourPrimitiveId()];
	out.pours.push({ layer: pp?.getState_Layer(), net: pp?.getState_Net(), fills: o.getState_PourFills() });
}
for (const s of await eda.pcb_PrimitiveString.getAll()) out.silk.push([s.getState_Layer(), s.getState_Text(), r3(s.getState_X() / MM), r3(s.getState_Y() / MM), r3(s.getState_FontSize() / MM)]);
return out;
