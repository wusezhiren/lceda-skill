// ===== 原理图版式绘图函数（拼在 lib.js 之后、各页脚本之前） =====
// 版式：左侧接口栏 + 粗分隔线；电路区 2×2 分区（红色分隔线）；蓝色粗体模块标题；
// 电源/地用标准符号，模块内部直接连线，跨页信号用网络端口 + 页码。
const COL = { title: '#0000FF', sub: '#C000C0', line: '#C00000', note: '#333333', ref: '#C00000' };
const AL = { LT: 1, LM: 2, LB: 3, CT: 4, C: 5, CB: 6, RT: 7, RM: 8, RB: 9 };
const P = {};
const LABELS = [];

async function openPage(name) {
	const pg = (await eda.dmt_Schematic.getAllSchematicPagesInfo()).find(p => p.name === name);
	must(pg, '没有图页 ' + name);
	await eda.dmt_EditorControl.openDocument(pg.uuid);
	await sleep(1200);
	return pg;
}

async function clearPage() {
	const comps = (await eda.sch_PrimitiveComponent.getAll()).filter(c => String(c.getState_ComponentType()) !== 'sheet');
	if (comps.length) await eda.sch_PrimitiveComponent.delete(comps.map(c => c.getState_PrimitiveId()));
	for (const k of ['sch_PrimitiveWire', 'sch_PrimitiveText', 'sch_PrimitiveRectangle', 'sch_PrimitivePolygon']) {
		const all = (await eda[k].getAll()) || [];
		if (all.length) await eda[k].delete(all.map(o => o.getState_PrimitiveId()));
	}
}

const r2 = v => Math.round(v * 100) / 100;

// 放器件；side：两脚器件的属性文字位置（'auto' | 'L' | 'R' | 'U' | 'D' | 'keep'）
async function place(ref, lcsc, x, y, rot = 0, mirror = false, side = 'auto') {
	const d = await deviceByLcsc(lcsc);
	const c = await eda.sch_PrimitiveComponent.create({ libraryUuid: d.libraryUuid, uuid: d.uuid }, x, y, undefined, rot, mirror);
	must(c, `放置 ${ref} ${lcsc} 失败`);
	const id = c.getState_PrimitiveId();
	await eda.sch_PrimitiveComponent.modify(id, { designator: ref });
	const readPins = async () => {
		const pins = {};
		for (const p of await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id))
			pins[p.pinNumber] = { x: r2(p.x), y: r2(p.y), rot: ((Math.round(p.rotation) % 360) + 360) % 360, name: p.pinName };
		return pins;
	};
	let pins = await readPins();
	// 两脚器件的符号引脚长度不统一（±15 / ±20）：把 1 脚平移到按 ±20 设计的位置，连线始终正交
	if (Object.keys(pins).length === 2 && pins['1']) {
		const e = { 0: [x - 20, y], 90: [x, y + 20], 180: [x + 20, y], 270: [x, y - 20] }[((rot % 360) + 360) % 360];
		const dx = e[0] - pins['1'].x, dy = e[1] - pins['1'].y;
		if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
			await eda.sch_PrimitiveComponent.modify(id, { x: x + dx, y: y + dy });
			pins = await readPins();
		}
	}
	P[ref] = { id, x, y, rot, pins };
	if (Object.keys(pins).length === 2 && side !== 'keep') {
		const pv = Object.values(pins);
		const x = (pv[0].x + pv[1].x) / 2, y = (pv[0].y + pv[1].y) / 2;
		const vertical = rot % 180 !== 0;
		const s = side === 'auto' ? (vertical ? 'R' : 'U') : side;
		const attrs = await eda.sch_PrimitiveAttribute.getAll(id);
		const des = attrs.find(a => a.getState_Key() === 'Designator');
		const nam = attrs.find(a => a.getState_Key() === 'Name');
		const pos = {
			R: [[x + 8, y + 1, AL.LB], [x + 8, y - 1, AL.LT]],
			L: [[x - 8, y + 1, AL.RB], [x - 8, y - 1, AL.RT]],
			U: [[x, y + 7, AL.CB], [x, y - 7, AL.CT]],
			D: [[x, y - 7, AL.CT], [x, y - 15, AL.CT]],
		}[s];
		if (des) await eda.sch_PrimitiveAttribute.modify(des.getState_PrimitiveId(), { x: pos[0][0], y: pos[0][1], alignMode: pos[0][2], rotation: 0 });
		if (nam) await eda.sch_PrimitiveAttribute.modify(nam.getState_PrimitiveId(), { x: pos[1][0], y: pos[1][1], alignMode: pos[1][2], rotation: 0 });
	}
	return P[ref];
}

// 'R1.2' → [x, y]；数组原样返回
function pt(p) {
	if (Array.isArray(p)) return p;
	const i = p.lastIndexOf('.');
	const ref = p.slice(0, i), num = p.slice(i + 1);
	must(P[ref], '未放置 ' + ref);
	const q = P[ref].pins[num] || Object.values(P[ref].pins).find(v => v.name === num);
	must(q, `${ref} 没有引脚 ${num}（有 ${Object.keys(P[ref].pins).join(',')}）`);
	return [q.x, q.y];
}

async function setNameAttrs(wireId, label) {
	const attrs = (await eda.sch_PrimitiveAttribute.getAll(wireId)).filter(a => ['Name', 'NET'].includes(a.getState_Key()));
	for (let i = 0; i < attrs.length; i++) {
		const id = attrs[i].getState_PrimitiveId();
		if (label && i === 0) await eda.sch_PrimitiveAttribute.modify(id, { x: label.x, y: label.y, alignMode: label.align, rotation: 0, fontSize: 7, keyVisible: false, valueVisible: true });
		else await eda.sch_PrimitiveAttribute.modify(id, { valueVisible: false, keyVisible: false });
	}
}

// 不显示网络名的导线（模块内部直接连线）
// 内部导线先不命名；flushLabels 时只给“本页既无标签、也无电源/地符号、也无端口”的网络补一次名，
// 避免 DRC“一个网络多个网络名”警告，同时保证 CC1、PMOS_G 等局部网络有可读名称
const WIRES = [];
const NAMED = new Set();
async function W(net, ...pts) {
	const line = pts.map(pt).flat();
	let w;
	try { w = await eda.sch_PrimitiveWire.create(line); }
	catch (e) { throw new Error(`连线 ${net} ${JSON.stringify(line)} 失败：${e.message || e}`); }
	must(w, `连线 ${net} 失败 ${JSON.stringify(line)}`);
	WIRES.push([w.getState_PrimitiveId(), net]);
	return w;
}

// 带网络标签的短线：from → to，标签放在 to 端的导线上方；最后统一创建
function NL(net, from, to) { LABELS.push([net, from, to]); }

async function flushLabels() {
	for (const [net] of LABELS) NAMED.add(net);
	for (const [id, net] of WIRES) {
		if (NAMED.has(net)) continue;
		NAMED.add(net);
		await eda.sch_PrimitiveWire.modify(id, { net });
		await setNameAttrs(id, null);
	}
	WIRES.length = 0;
	for (const [kind, net, [x, y]] of FLAGS) must(await eda.sch_PrimitiveComponent.createNetFlag(kind, net, x, y, 0), `符号 ${net} 失败`);
	FLAGS.length = 0;
	for (const [net, from, to] of LABELS) {
		const a = pt(from), b = pt(to);
		let w;
		try { w = await eda.sch_PrimitiveWire.create([...a, ...b], net); }
		catch (e) { throw new Error(`标签线 ${net} ${JSON.stringify([a, b])} 失败：${e.message || e}`); }
		must(w, `标签线 ${net} 失败`);
		const left = b[0] < a[0];
		await setNameAttrs(w.getState_PrimitiveId(), { x: b[0], y: b[1] + 1, align: left ? AL.LB : AL.RB });
	}
	LABELS.length = 0;
}

const FLAGS = [];
// 电源/地符号延后到导线之后创建：先放符号后画线时，导线不会并入符号的网络
async function GND(p) { NAMED.add('GND'); FLAGS.push(['Ground', 'GND', pt(p)]); }
async function PWR(net, p) { NAMED.add(net); FLAGS.push(['Power', net, pt(p)]); }

async function T(x, y, s, size = 7, color = COL.note, bold = false, align = AL.LB) {
	return eda.sch_PrimitiveText.create(x, y, s, 0, color, null, size, bold, false, false, align);
}
async function NC(p) { const [x, y] = pt(p); return T(x, y, '×', 8, '#0000FF', false, AL.C); }
async function LINE(pts, color = COL.line, width = 1) {
	return eda.sch_PrimitivePolygon.create(pts.flat(), color, 'none', width);
}
async function RECT(x, y, w, h, color = COL.line, width = 1) {
	return eda.sch_PrimitiveRectangle.create(x, y, w, h, 0, 0, color, 'none', width);
}
async function ARROW(pts, color = COL.note) {
	await LINE(pts, color, 1);
	const [x1, y1] = pts[pts.length - 2], [x2, y2] = pts[pts.length - 1];
	const L = Math.hypot(x2 - x1, y2 - y1), ux = (x2 - x1) / L, uy = (y2 - y1) / L, s = 6;
	const tri = [x2, y2, x2 - ux * s - uy * s / 2, y2 - uy * s + ux * s / 2, x2 - ux * s + uy * s / 2, y2 - uy * s - ux * s / 2, x2, y2];
	await eda.sch_PrimitivePolygon.create(tri, color, color, 1);
}

// 电路页公共框架：左侧接口栏 + 2×2 分区；标题栏保留区 x≥455、y≤215
async function frame(pageNo, title, summary) {
	await LINE([[150, 25], [150, 800]], COL.line, 3);
	await LINE([[650, 222], [650, 800]], COL.line, 1);
	await LINE([[150, 420], [1150, 420]], COL.line, 1);
	await T(25, 785, `P${pageNo}  ${title}`, 10, COL.title, true);
	let y = 768;
	for (const s of summary) { await T(25, y, s, 6); y -= 11; }
	await T(25, 690, '跨页接口 / Ports:', 8, COL.title, true);
}

// 跨页端口：页码文字 + 端口符号 + 带标签短线
async function PORT(net, y, pages, dir = 'BI') {
	await T(22, y, pages, 6, COL.ref, false, AL.LM);
	await eda.sch_PrimitiveComponent.createNetPort(dir, net, 75, y, 180);
	NL(net, [75, y], [140, y]);
}
async function QT(x, y, s) { return T(x, y, s, 12, COL.title, true); }

// 输出端口（显示网络名），用于 OUT+、RF_ANT 等仅在 PCB 落焊盘/天线的网络
async function OPORT(net, p) {
	NAMED.add(net);
	const [x, y] = pt(p);
	const c = await eda.sch_PrimitiveComponent.createNetPort('OUT', net, x, y, 0);
	const a = (await eda.sch_PrimitiveAttribute.getAll(c.getState_PrimitiveId())).find(a => a.getState_Key() === 'Name');
	if (a) await eda.sch_PrimitiveAttribute.modify(a.getState_PrimitiveId(), { valueVisible: true, x: x + 45, y, alignMode: AL.LM, fontSize: 7 });
	return c;
}

// 补齐库记录缺失的属性（例如部分系统库器件 Manufacturer Part 为空）
async function setAttr(ref, kv) {
	const attrs = await eda.sch_PrimitiveAttribute.getAll(P[ref].id);
	for (const [k, v] of Object.entries(kv)) {
		const a = attrs.find(a => a.getState_Key() === k);
		must(a, `${ref} 没有属性 ${k}`);
		await eda.sch_PrimitiveAttribute.modify(a.getState_PrimitiveId(), { value: v });
	}
}
