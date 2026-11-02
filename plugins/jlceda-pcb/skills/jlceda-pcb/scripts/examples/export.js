// 导出当前工程的生产文件（不需要“外部交互权限”，经 base64 回传，由 lceda.py 写盘）
// 运行：python3 lceda.py run examples/export.js --out jlceda/ --timeout 300
await openPcb();
const prefix = ARGS.prefix || 'board';
return {
	gerber: await fileOut(await eda.pcb_ManufactureData.getGerberFile(`${prefix}_Gerber`), 'gerber.zip'),
	bom: await fileOut(await eda.pcb_ManufactureData.getBomFile(`${prefix}_BOM`, 'csv'), 'BOM.csv'),
	cpl: await fileOut(await eda.pcb_ManufactureData.getPickAndPlaceFile(`${prefix}_CPL`, 'csv'), 'CPL.csv'),
};
