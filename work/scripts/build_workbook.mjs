import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputDir = process.argv[2];
const outputDir = process.argv[3];

if (!inputDir || !outputDir) {
  console.error("Usage: node build_workbook.mjs <csv-dir> <output-dir>");
  process.exit(2);
}

const csvSheets = [
  ["master_lexicon.csv", "Master"],
  ["verbs_by_transitivity.csv", "Verbs"],
  ["adjective_clusters.csv", "Adjectives"],
  ["noun_kanji_tree.csv", "Noun_Kanji_Tree"],
  ["cluster_summary.csv", "Cluster_Summary"],
  ["source_audit.csv", "Source_Audit"],
];

function columnName(n) {
  let name = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function countRows(csvText) {
  const normalized = csvText.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return normalized.endsWith("\n")
    ? normalized.slice(0, -1).split("\n").length
    : normalized.split("\n").length;
}

function countHeaderCols(csvText) {
  const firstLine = csvText.split(/\r?\n/, 1)[0] || "";
  return firstLine.split(",").length;
}

let workbook = null;
const sheetMeta = [];
for (const [filename, sheetName] of csvSheets) {
  const csvText = await fs.readFile(path.join(inputDir, filename), "utf8");
  if (workbook === null) {
    workbook = await Workbook.fromCSV(csvText, { sheetName });
  } else {
    await workbook.fromCSV(csvText, { sheetName });
  }
  sheetMeta.push({
    sheetName,
    rows: countRows(csvText),
    cols: countHeaderCols(csvText),
  });
}

const policy = workbook.worksheets.add("Policy");
policy.getRange("A1:B11").values = [
  ["项目", "说明"],
  ["范围", "A+B+C 现代标准语词汇：A/B 为核心和普通成人词汇，C 为低频但有 JMdict priority 或 BCCWJ rank 证据的现代可见候补。"],
  ["排除", "古语、废语、方言、生僻/罕用、请求范围外品词；无 priority 且无 BCCWJ 证据的冷词不进入主表。专有名词按 JMdict 词性原样收录，不另设特殊字段。"],
  ["词条来源", "JMdict/EDRDG，机器可读词条、读音、词性、自他、常用度标签。"],
  ["翻译来源", "中文翻译统一由 DeepSeek V4 Flash 基于 JMdict/EDRDG 英文释义生成；翻译来源栏使用短标签展示模型来源。"],
  ["汉字来源", "KANJIDIC2/EDRDG，辅助名词汉字树的音读/训读和常用汉字状态。"],
  ["国語辞典口径", "以现代一般国語辞典（デジタル大辞泉、精選版 日本国語大辞典等）作为收录语感和抽样复核参照。"],
  ["JMdict URL", "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"],
  ["KANJIDIC2 URL", "http://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz"],
  ["注意", "C 类为扩充候补，词群和自他对应候补为规则抽取结果，已在“复核状态”中标明，适合继续人工审校。"],
  ["生成日期", new Date().toISOString().slice(0, 10)],
];

const headerFill = "#1F4E78";
const subHeaderFill = "#EAF2F8";
const borderColor = "#D9E2EC";

for (const { sheetName, rows, cols } of sheetMeta) {
  const sheet = workbook.worksheets.getItem(sheetName);
  sheet.showGridLines = false;
  const lastCol = columnName(cols);
  sheet.freezePanes.freezeRows(1);
  sheet.getRange(`A1:${lastCol}1`).format = {
    fill: headerFill,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#173B57" },
  };
  const styledRows = Math.min(rows, 500);
  const visibleRange = sheet.getRange(`A1:${lastCol}${Math.max(styledRows, 1)}`);
  visibleRange.format.borders = {
    insideHorizontal: { style: "thin", color: borderColor },
    insideVertical: { style: "thin", color: "#EEF2F6" },
    bottom: { style: "thin", color: borderColor },
  };
  visibleRange.format.autofitColumns();
  visibleRange.format.autofitRows();
  if (sheetName === "Master") {
    sheet.getRange(`A1:${lastCol}${styledRows}`).format.columnWidth = 18;
    sheet.getRange(`O1:O${styledRows}`).format.columnWidth = 40;
    sheet.getRange(`P1:P${styledRows}`).format.columnWidth = 42;
    sheet.getRange(`Q1:Q${styledRows}`).format.columnWidth = 36;
    sheet.getRange(`U1:U${styledRows}`).format.columnWidth = 28;
    sheet.getRange(`X1:X${styledRows}`).format.columnWidth = 22;
  } else if (sheetName === "Noun_Kanji_Tree") {
    sheet.getRange(`A1:K${styledRows}`).format.columnWidth = 18;
    sheet.getRange(`E1:E${styledRows}`).format.columnWidth = 46;
  } else if (sheetName === "Source_Audit") {
    sheet.getRange(`A1:C${styledRows}`).format.columnWidth = 24;
    sheet.getRange(`C1:C${styledRows}`).format.columnWidth = 70;
  }
  if (rows > 1 && cols > 1 && rows <= 5000) {
    const tableRange = `A1:${lastCol}${rows}`;
    const tableName = `${sheetName.replace(/[^A-Za-z0-9_]/g, "")}Table`.slice(0, 250);
    try {
      const table = sheet.tables.add(tableRange, true, tableName);
      table.style = "TableStyleMedium2";
      table.showFilterButton = true;
    } catch {
      // Tables are a convenience; formatting above is still sufficient if a
      // large sheet or duplicate range prevents table creation.
    }
  }
}

policy.showGridLines = false;
policy.freezePanes.freezeRows(1);
policy.getRange("A1:B1").format = {
  fill: headerFill,
  font: { bold: true, color: "#FFFFFF" },
};
policy.getRange("A2:B11").format = {
  fill: subHeaderFill,
  borders: { preset: "inside", style: "thin", color: borderColor },
  wrapText: true,
};
policy.getRange("A1:A11").format.columnWidth = 18;
policy.getRange("B1:B11").format.columnWidth = 96;
policy.getRange("A1:B11").format.autofitRows();

await fs.mkdir(outputDir, { recursive: true });

const masterCheck = await workbook.inspect({
  kind: "table",
  sheetId: "Master",
  range: "A1:X8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 24,
  maxChars: 5000,
});
console.log(masterCheck.ndjson);

const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
  maxChars: 2000,
});
console.log(errorCheck.ndjson);

const preview = await workbook.render({
  sheetName: "Master",
  range: "A1:X25",
  scale: 1,
  format: "png",
});
await fs.writeFile(path.join(outputDir, "master_preview.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(outputDir, "yuki_jisho.xlsx"));
