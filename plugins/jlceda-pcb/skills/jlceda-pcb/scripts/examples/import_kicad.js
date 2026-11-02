// 导入路线：KiCad 工程 zip → 嘉立创EDA 新工程 → 立创编号写进供应商字段 → 过孔规则按嘉立创工艺 → 重铺铜 → DRC
// zip 用 make_kicad_zip.sh 生成（文件在根目录、去掉 3D 模型，base64 后需 < 1MB）
// 运行：python3 lceda.py run examples/import_kicad.js --in board.zip --args '{"zip":"board.zip","name":"my_board"}' --timeout 900
const team = (await eda.dmt_Team.getAllTeamsInfo())[0].uuid;
const r = await eda.sys_FileManager.importProjectByProjectFile(fileIn(ARGS.zip), 'KiCad', undefined,
	{ operation: 'New Project', newProjectOwnerTeamUuid: team, newProjectName: ARGS.name, newProjectFriendlyName: ARGS.name });
must(r && r.uuid, '导入失败：zip 里文件要在根目录（不要多套一层文件夹），且包含 .kicad_pro/.kicad_sch/.kicad_pcb');
await eda.dmt_Project.openProject(r.uuid);
await sleep(3000);
await openPcb();
await sleep(2000);

// KiCad 符号里的 LCSC 字段导入后只是自定义属性，下单要的是“供应商编号”
const lcscKey = ARGS.lcscField || 'LCSC';
let mapped = 0; const noLcsc = [];
for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
	const lcsc = (c.getState_OtherProperty() || {})[lcscKey];
	if (lcsc) { await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), { supplier: 'LCSC', supplierId: lcsc }); mapped++; }
	else { noLcsc.push(c.getState_Designator()); await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), { addIntoBom: false }); }
}
const rule = await setJlcViaRule();
const pours = await rebuildPours();
await eda.pcb_Document.save();
const counts = {
	comps: (await eda.pcb_PrimitiveComponent.getAll()).length,
	lines: (await eda.pcb_PrimitiveLine.getAll()).length,
	vias: (await eda.pcb_PrimitiveVia.getAll()).length,
};
return { project: r.uuid, mapped, notInBom: noLcsc, rule, pours, counts, drc: await drcSummary() };
