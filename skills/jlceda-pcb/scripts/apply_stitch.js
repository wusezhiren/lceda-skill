// 下发 gnd_stitch.py / gnd_route.py / chamfer.py 的结果，可选重铺铜 + DRC 摘要。
// ARGS = { del:[[net,layer,[x1,y1],[x2,y2]]],      // 先删：按网络+层+端点（mm，±0.006）匹配走线
//          vias:[[net,x,y]], via:[外径,孔径] mm,     // 默认 [0.45,0.2]（gnd_route.py 输出里自带 via）
//          lines:[[net,layer,[[x,y],...],w]],        // 折线逐段建
//          pour:true, drc:true }                     // 默认都做：重铺铜、返回 DRC 摘要
// 用法：python3 scripts/lceda.py run scripts/apply_stitch.js --args-file out.json --timeout 600
await openPcb();
const [vd, vh] = ARGS.via || [0.45, 0.2];
const near = (a, b) => Math.abs(a - b) < 0.006;
let nd = 0, nv = 0, nl = 0, miss = 0;
if ((ARGS.del || []).length) {
	const info = (await eda.pcb_PrimitiveLine.getAll()).map(l => ({ l, net: l.getState_Net(), L: l.getState_Layer(),
		a: [l.getState_StartX() / MM, l.getState_StartY() / MM], b: [l.getState_EndX() / MM, l.getState_EndY() / MM] }));
	const eq = (p, q) => near(p[0], q[0]) && near(p[1], q[1]);
	for (const [net, L, p, q] of ARGS.del) {
		const o = info.find(o => !o.gone && o.net === net && o.L === L && ((eq(o.a, p) && eq(o.b, q)) || (eq(o.a, q) && eq(o.b, p))));
		if (!o) { miss++; continue; }
		await eda.pcb_PrimitiveLine.delete([o.l.getState_PrimitiveId()]); o.gone = true; nd++;
	}
}
for (const [net, x, y] of ARGS.vias || []) { if (await eda.pcb_PrimitiveVia.create(net, mm(x), mm(y), mm(vh), mm(vd))) nv++; }
for (const [net, layer, pts, w] of ARGS.lines || [])
	for (let i = 0; i + 1 < pts.length; i++)
		if (await eda.pcb_PrimitiveLine.create(net, layer, mm(pts[i][0]), mm(pts[i][1]), mm(pts[i + 1][0]), mm(pts[i + 1][1]), mm(w))) nl++;
if (ARGS.pour !== false) await rebuildPours();
await eda.pcb_Document.save();
const out = { deleted: nd, delMissing: miss, vias: nv, lines: nl };
if (ARGS.drc !== false) {
	const s = await drcSummary(6);
	out.drc = s.total;
	out.groups = Object.fromEntries(Object.entries(s.groups).map(([k, g]) => [k, g.at.map((p, i) => `${p.join(',')} ${g.objs[i]}`)]));
}
return out;
