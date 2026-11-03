// ===== jlceda-pcb 公共函数（lceda.py 会把本文件拼在每个脚本前面） =====
// 坐标单位：原理图 = 0.01 inch（10mil）；PCB = mil。

let __sysLib = null;
async function sysLib() {
	if (!__sysLib) __sysLib = await eda.lib_LibrariesList.getSystemLibraryUuid();
	return __sysLib;
}

// 按立创 C 编号取系统库器件（getByLcscIds 在 4.1.93 返回空，用 searchByProperties）
async function deviceByLcsc(lcsc) {
	const r = await eda.lib_Device.searchByProperties({ supplierId: lcsc }, undefined, undefined, undefined, 5, 1);
	const d = (r || []).find(x => (x.otherProperty || {})['Supplier Part'] === lcsc) || (r || [])[0];
	if (!d) throw new Error(`系统库里找不到 ${lcsc}`);
	return { ...d, libraryUuid: d.libraryUuid || await sysLib() };
}

// 器件的简要信息：库类型（基础/扩展）、封装、型号
function brief(d) {
	const p = d.otherProperty || {};
	return {
		lcsc: p['Supplier Part'], name: d.name, mpn: p['Manufacturer Part'],
		footprint: (d.footprint || {}).name || d.footprintName,
		jlcClass: p['JLCPCB Part Class'], // "Basic Part" / "Extended Part"
	};
}

function must(cond, msg) { if (!cond) throw new Error(msg); }

// ---------------- 原理图 ----------------
const DIR = { 0: [1, 0], 90: [0, 1], 180: [-1, 0], 270: [0, -1] };

// 放器件：lcsc → 位号；返回 {id, pins:{号:{x,y,rot,name}}}
async function schPlace(lcsc, designator, x, y, rotation = 0) {
	const d = await deviceByLcsc(lcsc);
	const c = await eda.sch_PrimitiveComponent.create({ libraryUuid: d.libraryUuid, uuid: d.uuid }, x, y, undefined, rotation);
	must(c, `放置 ${lcsc} 失败`);
	const id = c.getState_PrimitiveId();
	if (designator) await eda.sch_PrimitiveComponent.modify(id, { designator });
	const pins = {};
	for (const p of await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id))
		pins[p.pinNumber] = { x: p.x, y: p.y, rot: ((p.rotation % 360) + 360) % 360, name: p.pinName };
	return { id, designator, lcsc, pins };
}

// 在引脚端点沿引脚朝向画一段带网络名的短线（同名网络自动连通）
async function schNet(pin, net, len = 20) {
	const [dx, dy] = DIR[pin.rot] || [1, 0];
	const w = await eda.sch_PrimitiveWire.create([pin.x, pin.y, pin.x + dx * len, pin.y + dy * len], net);
	must(w, `连线 ${net} 失败`);
	return w;
}

// 引脚号或引脚名找引脚
function pinOf(part, key) {
	const k = String(key);
	const p = part.pins[k] || Object.values(part.pins).find(p => p.name === k);
	must(p, `${part.designator} 没有引脚 ${k}（有: ${Object.entries(part.pins).map(([n, p]) => n + ':' + p.name).join(' ')}）`);
	return p;
}

// ---------------- 界面对话框（通过 top.document 自动点击） ----------------
const sleep = ms => new Promise(r => setTimeout(r, ms));

function visibleButtons() {
	return [...top.document.querySelectorAll('button, .ant-btn, [role=button]')]
		.filter(b => b.offsetParent !== null && !b.disabled);
}

// 等待并点击文字匹配的按钮（texts 按优先级），返回点到的文字或 null
async function clickButton(texts, timeoutMs = 15000) {
	const t0 = Date.now();
	while (Date.now() - t0 < timeoutMs) {
		const btns = visibleButtons();
		for (const t of texts) {
			const b = btns.find(b => (b.innerText || '').trim() === t);
			if (b) { b.click(); return t; }
		}
		await sleep(300);
	}
	return null;
}

// 原理图 → PCB 导入变更，自动点“应用修改”
async function importToPcb() {
	const b = await firstBoard();
	await eda.dmt_EditorControl.openDocument(b.pcb.uuid);
	await sleep(1000);
	const p = eda.pcb_Document.importChanges(b.schematic.uuid);
	const clicked = await clickButton(['应用修改', 'Apply Changes'], 20000);
	const ok = await p;
	await sleep(1000);
	return { ok, clicked };
}

// ---------------- PCB ----------------
const MM = 39.3700787;              // 1mm = 39.37mil（PCB 坐标单位为 mil）
const mm = v => v * MM;

// 刚 openProject 后板子信息要过一会儿才加载出来，轮询等待
async function firstBoard(timeoutMs = 30000) {
	const t0 = Date.now();
	while (Date.now() - t0 < timeoutMs) {
		const b = ((await eda.dmt_Board.getAllBoardsInfo()) || [])[0];
		if (b && b.pcb && b.schematic) return b;
		await new Promise(r => setTimeout(r, 1000));
	}
	throw new Error('等待工程加载超时：没有找到 Board（工程是否打开？）');
}

async function openPcb() {
	const b = await firstBoard();
	await eda.dmt_EditorControl.openDocument(b.pcb.uuid);
	await sleep(800);
	return b;
}

// 矩形板框（单位 mm，左下角 (x0,y0)；PCB 的 Y 轴向上）
async function boardOutline(wMm, hMm, x0 = 0, y0 = 0) {
	for (const l of await eda.pcb_PrimitivePolyline.getAll(undefined, EPCB_LayerId.BOARD_OUTLINE))
		await eda.pcb_PrimitivePolyline.delete([l.getState_PrimitiveId()]);
	const [X0, Y0, X1, Y1] = [mm(x0), mm(y0), mm(x0 + wMm), mm(y0 + hMm)];
	const poly = eda.pcb_MathPolygon.createPolygon([X0, Y0, 'L', X1, Y0, X1, Y1, X0, Y1, X0, Y0]);
	return eda.pcb_PrimitivePolyline.create('', EPCB_LayerId.BOARD_OUTLINE, poly, 6);
}

// 按位号摆件：place = {Q1:[xmm, ymm, rot, 'TOP'|'BOTTOM'], ...}
async function pcbPlace(place) {
	const comps = await eda.pcb_PrimitiveComponent.getAll();
	const miss = [];
	for (const c of comps) {
		const p = place[c.getState_Designator()];
		if (!p) { miss.push(c.getState_Designator()); continue; }
		const [x, y, rot = 0, side = 'TOP'] = p;
		await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(),
			{ x: mm(x), y: mm(y), rotation: rot, layer: side === 'BOTTOM' ? EPCB_LayerId.BOTTOM : EPCB_LayerId.TOP });
	}
	return { placed: comps.length - miss.length, unplaced: miss };
}

// 两面整板铺 GND（矩形，单位 mm）
async function pourGnd(wMm, hMm, x0 = 0, y0 = 0, net = 'GND') {
	const pts = [mm(x0), mm(y0), 'L', mm(x0 + wMm), mm(y0), mm(x0 + wMm), mm(y0 + hMm), mm(x0), mm(y0 + hMm), mm(x0), mm(y0)];
	const res = [];
	for (const layer of [EPCB_LayerId.TOP, EPCB_LayerId.BOTTOM]) {
		const cp = eda.pcb_MathPolygon.createComplexPolygon([pts]);
		res.push(await eda.pcb_PrimitivePour.create(net, layer, cp, EPCB_PrimitivePourFillMethod.SOLID, true, `${net}_${layer}`));
	}
	return res.map(r => !!r);
}

async function drc() {
	const v = await eda.pcb_Drc.check(true, false, true);
	return Array.isArray(v) ? v : [];
}

// ---------------- 文件进出（base64，不需要“外部交互权限”） ----------------
// 返回值里的 {__file__: 文件名, b64} 会被 lceda.py 写到 --out 目录
async function fileOut(file, name) {
	must(file, `没有生成 ${name}`);
	const buf = new Uint8Array(await file.arrayBuffer());
	let s = '';
	for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
	return { __file__: name || file.name, b64: btoa(s), size: buf.length };
}

// lceda.py --in 传进来的文件：INFILES[文件名] → File
function fileIn(name) {
	const b64 = (typeof INFILES !== 'undefined' && INFILES[name]);
	must(b64, `没有传入文件 ${name}`);
	const bin = atob(b64);
	const u = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
	return new File([u], name);
}

// DRC 结果是多层嵌套分组；摊平成 {“类型 / 对象”: {count, at:[[xmm,ymm]...], objs}} 方便阅读
async function drcSummary(maxAt = 4) {
	const v = await drc();
	const leaves = [];
	(function walk(n) {
		if (Array.isArray(n)) return n.forEach(walk);
		if (n && typeof n === 'object') {
			if (n.errorType && n.pos) leaves.push(n);
			else if (n.list) walk(n.list);
		}
	})(v);
	const sum = {};
	for (const e of leaves) {
		const k = `${e.errorType} / ${e.errorObjType}`;
		const s = sum[k] = sum[k] || { count: 0, at: [], objs: [] };
		s.count++;
		if (s.at.length < maxAt) {
			s.at.push([+(e.pos.x / MM).toFixed(2), +(e.pos.y / MM).toFixed(2)]);
			s.objs.push(`${e.obj1?.typeName}${e.obj1?.suffix || ''} ↔ ${e.obj2?.typeName}${e.obj2?.suffix || ''}`);
		}
	}
	return { total: leaves.length, groups: sum };
}

// 按嘉立创 2 层板工艺放宽过孔规则：孔径 ≥0.3mm、外径 ≥0.5mm（导入工程的默认规则要求孔径 ≥0.5mm）
// 注意：规则里 viaInnerdiameter* 实际是“孔径”，viaOuterdiameter* 实际是“外径”，字段名与含义相反，以 DRC 报错文字为准
async function setJlcViaRule(holeMinMm = 0.3, diaMinMm = 0.5) {
	const cfg = await eda.pcb_Drc.getCurrentRuleConfiguration();
	const f = cfg.config.Physics['Via Size'].viaSize.form;
	f.viaInnerdiameterMin = holeMinMm;
	f.viaOuterdiameterMin = Math.min(f.viaOuterdiameterMin, holeMinMm);
	if (f.viaInnerdiameterDefault < holeMinMm) f.viaInnerdiameterDefault = holeMinMm;
	return eda.pcb_Drc.overwriteCurrentRuleConfiguration(cfg.config);   // 传 config 字段本身
}

// 重新铺所有铺铜（导入的工程带的是别的软件算好的填充，不认禁布区）
async function rebuildPours() {
	let n = 0;
	for (const p of await eda.pcb_PrimitivePour.getAll()) { await p.rebuildCopperRegion(); n++; }
	await sleep(1500);
	return n;
}
