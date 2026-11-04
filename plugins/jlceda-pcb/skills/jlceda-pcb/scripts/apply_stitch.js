// 下发 gnd_stitch.py 的结果：ARGS = {vias:[[net,x,y]], lines:[[net,layer,[[x,y],[x,y]],w]], via:[外径,孔径] mm}
await openPcb();
const [vd, vh] = ARGS.via || [0.45, 0.2];
let nv = 0, nl = 0;
for (const [net, x, y] of ARGS.vias || []) { if (await eda.pcb_PrimitiveVia.create(net, mm(x), mm(y), mm(vh), mm(vd))) nv++; }
for (const [net, layer, pts, w] of ARGS.lines || [])
	for (let i = 0; i + 1 < pts.length; i++)
		if (await eda.pcb_PrimitiveLine.create(net, layer, mm(pts[i][0]), mm(pts[i][1]), mm(pts[i + 1][0]), mm(pts[i + 1][1]), mm(w))) nl++;
await eda.pcb_Document.save();
return { vias: nv, lines: nl };
