import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function parseArgs(argv) {
  const command = argv[0];
  const options = {};
  for (let index = 1; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`无效参数: ${token}`);
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`参数缺少值: ${token}`);
    options[key] = value;
    index += 1;
  }
  return { command, options };
}

function required(options, key) {
  if (!options[key]) throw new Error(`缺少参数 --${key}`);
  return options[key];
}

function normalizeHeader(value) {
  return String(value ?? "").trim().replace(/\s+/g, "").toLowerCase();
}

async function exportSource(options) {
  const input = required(options, "input");
  const output = required(options, "output");
  const start = Number(options.start || 1);
  const limit = Number(options.limit || 50);
  if (!Number.isInteger(start) || start < 1) throw new Error("--start 必须是大于等于1的整数");
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
  const sheet = options.sheet ? workbook.worksheets.getItem(options.sheet) : workbook.worksheets.getItemAt(0);
  const used = sheet.getUsedRange(true);
  const values = used?.values || [];
  if (values.length < 2) throw new Error("来源Excel没有数据行");
  const aliases = {
    "序号": ["序号", "index", "编号"],
    "趋势词": ["趋势词", "关键词", "搜索词"],
    "笔记标题": ["笔记标题", "标题"],
    "创建日期": ["创建日期", "发布日期", "发布时间"],
    "笔记链接": ["笔记链接", "链接", "url"],
    "笔记类型": ["笔记类型", "内容形式", "形式", "类型"],
    "作者名称": ["作者名称", "作者", "昵称"],
    "阅读量": ["阅读量", "阅读", "曝光量"],
    "互动量": ["互动量", "互动"],
  };
  const headers = values[0].map(normalizeHeader);
  const positions = {};
  for (const [name, candidates] of Object.entries(aliases)) {
    positions[name] = headers.findIndex((header) => candidates.map(normalizeHeader).includes(header));
  }
  if (positions["笔记链接"] < 0) throw new Error("来源Excel缺少链接列");
  const data = values.slice(start, start + limit).map((row, offset) => {
    const record = { source_row: start + offset + 1 };
    for (const name of Object.keys(aliases)) {
      const position = positions[name];
      record[name] = position >= 0 ? (row[position] ?? null) : null;
    }
    if (record["序号"] == null || record["序号"] === "") record["序号"] = start + offset;
    const url = String(record["笔记链接"] || "");
    record.note_id = url.match(/\/(?:item|explore)\/([^?]+)/)?.[1] || "";
    return record;
  });
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, JSON.stringify(data, null, 2));
  console.log(JSON.stringify({ output, start, rows: data.length, validLinks: data.filter((row) => row.note_id).length }));
}

const typeColors = {
  "教程攻略": "#D9EAF7",
  "痛点解决": "#FCE1E1",
  "科普知识": "#E8DDF5",
  "场景化故事": "#FCE4C7",
  "对比测评": "#FFF2CC",
  "KOL/KOC亲测": "#DDEED8",
  "行业观点": "#D9E1F2",
  "产品展示": "#E2F0D9",
  "其他未确认": "#E7E6E6",
};

async function buildReport(options) {
  const context = JSON.parse(await fs.readFile(required(options, "context"), "utf8"));
  const analysis = JSON.parse(await fs.readFile(required(options, "analysis"), "utf8"));
  const outputPath = required(options, "output");
  const byIndex = new Map(analysis.map((row) => [Number(row.index), row]));
  if (byIndex.size !== context.length) throw new Error(`分析结果应为${context.length}行，实际${byIndex.size}行`);

  const rows = context.map((row) => {
    const source = row.source || {};
    const note = row.note || {};
    const item = byIndex.get(Number(source["序号"] ?? source.index));
    if (!item) throw new Error(`缺少第${source["序号"] ?? source.index}行分析`);
    return [
      source["序号"] ?? source.index,
      source["趋势词"] || "",
      note.title || source["笔记标题"] || "",
      note.author || source["作者名称"] || "",
      source["创建日期"] || "",
      note.format || source["笔记类型"] || "",
      source["阅读量"] ?? null,
      source["互动量"] ?? null,
      note.likes ?? null,
      note.saves ?? null,
      note.comment_count ?? null,
      item.comment_focus || "",
      note.body || "",
      item.cover_ocr || row.images?.[0]?.ocr || "",
      item.cover_strategy || "",
      item.content_type || "其他未确认",
      item.commercial_judgment || "无法判断",
      item.brand_product || "",
      item.placement || "",
      item.high_read_method || "",
      row.transcription_status || "",
      row.status || "",
      item.evidence_gap || "",
      source["笔记链接"] || source.link || "",
    ];
  });

  const workbook = Workbook.create();
  const overview = workbook.worksheets.add("分析总览");
  const detail = workbook.worksheets.add("笔记明细");
  const failed = workbook.worksheets.add("无法读取");
  for (const sheet of [overview, detail, failed]) sheet.showGridLines = false;

  const headers = ["序号", "趋势词", "标题", "作者", "发布日期", "笔记形式", "原表阅读量", "原表互动量", "当前点赞", "当前收藏", "当前评论", "评论重点", "正文", "封面文字OCR", "封面策略", "内容类型", "商业判断", "品牌/产品", "产品植入", "高阅读做法", "字幕/转录状态", "采集状态", "证据缺口", "链接"];
  const endRow = rows.length + 1;
  detail.getRange("A1:X1").values = [headers];
  if (rows.length) detail.getRange(`A2:X${endRow}`).values = rows;
  detail.freezePanes.freezeRows(1);
  detail.freezePanes.freezeColumns(3);
  detail.getRange("A1:X1").format = {
    fill: "#2F5597", font: { bold: true, color: "#FFFFFF", size: 11 },
    horizontalAlignment: "center", verticalAlignment: "center", wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#1F3864" },
  };
  detail.getRange("A1:X1").format.rowHeight = 34;
  if (rows.length) {
    detail.getRange(`A2:X${endRow}`).format = { verticalAlignment: "top", wrapText: true, font: { size: 10 } };
    detail.getRange(`A2:X${endRow}`).format.rowHeight = 118;
    detail.getRange(`A2:K${endRow}`).format.horizontalAlignment = "center";
    detail.getRange(`G2:K${endRow}`).setNumberFormat("#,##0");
    detail.getRange(`A2:X${endRow}`).format.borders = {
      insideHorizontal: { style: "thin", color: "#E6E6E6" },
      bottom: { style: "thin", color: "#D9D9D9" },
    };
  }
  [8, 18, 32, 16, 12, 10, 13, 13, 12, 12, 12, 42, 58, 45, 40, 16, 12, 28, 52, 52, 24, 20, 38, 45]
    .forEach((width, index) => { detail.getRangeByIndexes(0, index, endRow, 1).format.columnWidth = width; });
  rows.forEach((row, index) => {
    const excelRow = index + 2;
    detail.getRange(`P${excelRow}`).format = {
      fill: typeColors[row[15]] || typeColors["其他未确认"], font: { bold: true },
      horizontalAlignment: "center", verticalAlignment: "center", wrapText: true,
    };
    if (row[21] !== "采集成功") {
      detail.getRange(`A${excelRow}:X${excelRow}`).format.fill = "#F2F2F2";
      detail.getRange(`V${excelRow}`).format = { fill: "#F4CCCC", font: { bold: true, color: "#9C0006" }, horizontalAlignment: "center", wrapText: true };
      detail.getRange(`P${excelRow}`).format.fill = typeColors["其他未确认"];
    }
  });

  const failedRows = rows.filter((row) => row[21] !== "采集成功").map((row) => [row[0], row[2], row[6], row[7], row[20], row[21], row[22], row[23]]);
  failed.getRange("A1:H1").values = [["序号", "标题", "原表阅读量", "原表互动量", "字幕/转录状态", "采集状态", "证据缺口", "链接"]];
  if (failedRows.length) failed.getRange(`A2:H${failedRows.length + 1}`).values = failedRows;
  failed.freezePanes.freezeRows(1);
  failed.getRange("A1:H1").format = { fill: "#A61C00", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
  if (failedRows.length) {
    failed.getRange(`A2:H${failedRows.length + 1}`).format = { wrapText: true, verticalAlignment: "top", fill: "#FCE8E6" };
    failed.getRange(`C2:D${failedRows.length + 1}`).setNumberFormat("#,##0");
    failed.getRange(`A2:H${failedRows.length + 1}`).format.rowHeight = 62;
  }
  [8, 38, 14, 14, 24, 24, 50, 55].forEach((width, index) => { failed.getRangeByIndexes(0, index, Math.max(1, failedRows.length + 1), 1).format.columnWidth = width; });

  overview.mergeCells("A1:H2");
  overview.getRange("A1").values = [["小红书批量笔记分析"]];
  overview.getRange("A1:H2").format = { fill: "#2F5597", font: { bold: true, color: "#FFFFFF", size: 20 }, horizontalAlignment: "center", verticalAlignment: "center" };
  overview.getRange("A4:H4").values = [["总样本", null, "采集成功", null, "失败/跳过", null, "图文/视频", null]];
  overview.getRange("B4").formulas = [[`=COUNTA('笔记明细'!A2:A${endRow})`]];
  overview.getRange("D4").formulas = [[`=COUNTIF('笔记明细'!V2:V${endRow},"采集成功")`]];
  overview.getRange("F4").formulas = [[`=COUNTIF('笔记明细'!V2:V${endRow},"<>采集成功")`]];
  overview.getRange("H4").formulas = [[`=COUNTIFS('笔记明细'!V2:V${endRow},"采集成功",'笔记明细'!F2:F${endRow},"图文")&" / "&COUNTIFS('笔记明细'!V2:V${endRow},"采集成功",'笔记明细'!F2:F${endRow},"视频")`]];
  overview.getRange("A4:H4").format = { fill: "#D9EAF7", font: { bold: true, color: "#1F3864", size: 12 }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#B4C7E7" } };
  overview.getRange("A4:H4").format.rowHeight = 48;
  overview.getRange("A7:B7").values = [["内容类型", "篇数"]];
  overview.getRange("D7:E7").values = [["颜色图例", "含义"]];
  overview.getRange("G7:H7").values = [["商业判断", "篇数"]];
  for (const range of ["A7:B7", "D7:E7", "G7:H7"]) overview.getRange(range).format = { fill: "#4472C4", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
  const types = Object.keys(typeColors);
  overview.getRange(`A8:A${7 + types.length}`).values = types.map((value) => [value]);
  overview.getRange(`B8:B${7 + types.length}`).formulas = types.map((value) => [`=COUNTIF('笔记明细'!P2:P${endRow},"${value}")`]);
  overview.getRange(`D8:D${7 + types.length}`).values = types.map((value) => [value]);
  overview.getRange(`E8:E${7 + types.length}`).values = types.map(() => ["按内容主结构分类"]);
  types.forEach((value, index) => {
    overview.getRange(`D${8 + index}`).format.fill = typeColors[value];
    overview.getRange(`D${8 + index}`).format.font = { bold: true };
  });
  const commercial = ["商业", "疑似商业", "非商业", "无法判断"];
  overview.getRange("G8:G11").values = commercial.map((value) => [value]);
  overview.getRange("H8:H11").formulas = commercial.map((value) => [`=COUNTIF('笔记明细'!Q2:Q${endRow},"${value}")`]);
  overview.mergeCells("A19:H19");
  overview.getRange("A19").values = [["采集与分析口径"]];
  overview.getRange("A19:H19").format = { fill: "#D9E1F2", font: { bold: true, color: "#1F3864" } };
  overview.getRange("A20:H23").merge(true);
  overview.getRange("A20:A23").values = [
    ["1. 采集最多4路并发；单篇60秒无响应即跳过；失败不重试。"],
    ["2. 图文下载封面及全部内页并做本地OCR；机械步骤不调用大模型。"],
    ["3. 视频优先官方字幕；无字幕先标记并跳过，不自动调用本地或云端转录。"],
    ["4. 封面策略、植入逻辑、高阅读做法等语义字段由Codex基于证据填写。"],
  ];
  overview.getRange("A20:H23").format = { wrapText: true, verticalAlignment: "center", fill: "#F7F9FC" };
  overview.getRange("A20:H23").format.rowHeight = 32;
  for (const column of ["A", "B", "C", "D", "E", "F", "G", "H"]) overview.getRange(`${column}1:${column}23`).format.columnWidth = 18;
  overview.freezePanes.freezeRows(2);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  console.log(JSON.stringify({ output: outputPath, rows: rows.length, success: rows.filter((row) => row[21] === "采集成功").length, failed: failedRows.length }));
}

async function verifyReport(options) {
  const input = required(options, "input");
  const outputPath = required(options, "output");
  const previewDir = required(options, "preview-dir");
  const expected = Number(required(options, "expected"));
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
  const names = [0, 1, 2].map((index) => workbook.worksheets.getItemAt(index).name);
  const detail = workbook.worksheets.getItem("笔记明细");
  const values = detail.getRange(`A1:X${expected + 1}`).values;
  const headers = values[0];
  const rows = values.slice(1);
  const checks = {
    sheets: JSON.stringify(names) === JSON.stringify(["分析总览", "笔记明细", "无法读取"]),
    rowCount: rows.length === expected,
    uniqueSequence: new Set(rows.map((row) => Number(row[0]))).size === expected,
    headers: headers[11] === "评论重点" && headers[15] === "内容类型" && headers[20] === "字幕/转录状态" && headers[23] === "链接",
    linksComplete: rows.every((row) => String(row[23] || "").startsWith("https://www.xiaohongshu.com/")),
    modelFieldsComplete: rows.filter((row) => row[21] === "采集成功").every((row) => row[14] && row[15] && row[18] && row[19] && row[22]),
  };
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "formula error scan" });
  checks.formulaErrors = errors.ndjson.includes("matched 0 entries");
  await fs.mkdir(previewDir, { recursive: true });
  for (const [sheetName, range, filename, scale] of [
    ["分析总览", "A1:H23", "overview.png", 1.2],
    ["笔记明细", `A1:X${Math.min(expected + 1, 8)}`, "detail.png", 0.8],
    ["无法读取", "A1:H12", "failed.png", 1.0],
  ]) {
    const preview = await workbook.render({ sheetName, range, scale, format: "png" });
    await fs.writeFile(path.join(previewDir, filename), new Uint8Array(await preview.arrayBuffer()));
  }
  const failedChecks = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
  const result = { checks, passed: Object.keys(checks).length - failedChecks.length, failed: failedChecks.length, failedChecks };
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if (failedChecks.length) process.exit(1);
}

const { command, options } = parseArgs(process.argv.slice(2));
if (command === "export-source") await exportSource(options);
else if (command === "build-report") await buildReport(options);
else if (command === "verify-report") await verifyReport(options);
else throw new Error(`未知命令: ${command}`);
