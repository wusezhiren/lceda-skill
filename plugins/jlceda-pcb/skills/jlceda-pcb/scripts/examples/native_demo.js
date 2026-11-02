// 原生路线最小示例：新建工程 → 按立创编号放器件 → 网络名连线 → 导入 PCB（自动点“应用修改”）
//                   → 板框 → 摆件 → 自动布线 → 铺 GND → DRC → 保存
// 运行：python3 lceda.py run examples/native_demo.js --args '{"name":"demo_switch"}' --timeout 600
const name = ARGS.name || 'demo_switch';

// 1. 工程（createProject 会自带 Board1 = Schematic1 + PCB1，不要再 createBoard）
const team = (await eda.dmt_Team.getAllTeamsInfo())[0].uuid;
const proj = await eda.dmt_Project.createProject(name, name, team);
must(proj, '新建工程失败（同名工程已存在？）');
await eda.dmt_Project.openProject(proj);
await sleep(1500);
const board = (await eda.dmt_Board.getAllBoardsInfo())[0];
const sch = await eda.dmt_Schematic.getSchematicInfo(board.schematic.uuid);
await eda.dmt_EditorControl.openDocument(sch.page[0].uuid);
await sleep(800);

// 2. 原理图：一路 N-MOS 低边开关（坐标单位 10mil）
const q = await schPlace('C20917', 'Q1', 1000, 1000);   // AO3400A
const rg = await schPlace('C25076', 'R1', 800, 1000);   // 100Ω 0402
const rpd = await schPlace('C25741', 'R2', 900, 900, 90); // 100k 0402
await schNet(pinOf(rg, '1'), 'CTRL');
await schNet(pinOf(rg, '2'), 'GATE');
await schNet(pinOf(q, 'G'), 'GATE');
await schNet(pinOf(rpd, '1'), 'GATE');
await schNet(pinOf(rpd, '2'), 'GND');
await schNet(pinOf(q, 'S'), 'GND');
await schNet(pinOf(q, 'D'), 'OUT');
await eda.sch_Document.save();

// 3. PCB
const imp = await importToPcb();
must(imp.ok, '导入 PCB 失败');
await boardOutline(15, 10);
const placed = await pcbPlace({ R1: [3, 5, 0], R2: [6, 3, 0], Q1: [9, 5, 0] });
const route = await eda.pcb_Document.autoRouting();
const pour = await pourGnd(15, 10);
const drcRes = await drcSummary();
await eda.pcb_Document.save();
return { proj, imp, placed, route, pour, drc: drcRes };
