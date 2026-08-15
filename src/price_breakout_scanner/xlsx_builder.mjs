import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const [dataPath, outputPath, runtimeDirectory] = process.argv.slice(2);
const requireFromRuntime = createRequire(path.join(runtimeDirectory, "entry.cjs"));
const { SpreadsheetFile, Workbook } = requireFromRuntime("@oai/artifact-tool");
const records = JSON.parse(await fs.readFile(dataPath, "utf8"));

const columns = [
  ["Rank", "rank"], ["Symbol", "symbol"], ["Company", "company"], ["Date", "date"],
  ["Price-Action Score", "score"], ["Setup", "setup"], ["Price", "price"],
  ["Resistance", "resistance"], ["Distance to Resistance %", "distance_to_resistance_pct"],
  ["Breakout %", "breakout_pct"], ["10D Range %", "range_10d_pct"],
  ["Tightening Ratio", "tightening_ratio"], ["Higher Low %", "higher_low_pct"],
  ["Current Volume Ratio", "volume_ratio"], ["5D Volume Contraction", "volume_contraction_ratio"],
  ["5D Momentum %", "momentum_5d_pct"], ["20D Momentum %", "momentum_20d_pct"],
  ["20D Extension %", "extension_20d_pct"], ["Weinstein Stage", "weinstein_stage"],
  ["Stage Source", "stage_source"], ["20D Dollar Volume", "dollar_volume_20d"],
  ["Legacy Atlas Score", "legacy_score"], ["Legacy Grade", "grade"],
];
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Candidates");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
const matrix = [columns.map(([header]) => header), ...records.map((record) => columns.map(([, key]) => record[key] ?? null))];
const rowCount = Math.max(matrix.length, 1);
const columnCount = columns.length;
const used = sheet.getRangeByIndexes(0, 0, rowCount, columnCount);
used.values = matrix;
used.format.font = { name: "Menlo Regular", size: 16, color: "#1F2937" };
used.format.verticalAlignment = "center";
used.format.autofitRows();
const header = sheet.getRangeByIndexes(0, 0, 1, columnCount);
header.format.fill = "#17365D";
header.format.font = { name: "Menlo Regular", size: 16, bold: true, color: "#FFFFFF" };
header.format.rowHeight = 30;

if (records.length) {
  const table = sheet.tables.add(used, true, "PriceActionCandidates");
  table.showBandedRows = true;
  table.showFilterButton = true;
  sheet.getRangeByIndexes(1, 4, records.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 6, records.length, 2).format.numberFormat = "$#,##0.00";
  sheet.getRangeByIndexes(1, 8, records.length, 2).format.numberFormat = "0.00\"%\"";
  sheet.getRangeByIndexes(1, 10, records.length, 3).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 13, records.length, 2).format.numberFormat = "0.00\"x\"";
  sheet.getRangeByIndexes(1, 15, records.length, 3).format.numberFormat = "0.00\"%\"";
  sheet.getRangeByIndexes(1, 18, records.length, 1).format.numberFormat = "0";
  sheet.getRangeByIndexes(1, 20, records.length, 1).format.numberFormat = "$#,##0";
  sheet.getRangeByIndexes(1, 21, records.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 4, records.length, 1).conditionalFormats.add("colorScale", {
    thresholds: ["min", "50%", "max"], colors: ["#FECACA", "#FEF3C7", "#BBF7D0"],
  });
}
for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
  const longest = Math.max(...matrix.map((row) => String(row[columnIndex] ?? "").length));
  const widthPx = Math.min(420, Math.max(95, longest * 13 + 30));
  sheet.getRangeByIndexes(0, columnIndex, rowCount, 1).format.columnWidthPx = widthPx;
}

const methods = workbook.worksheets.add("Methodology");
methods.showGridLines = false;
methods.freezePanes.freezeRows(1);
const methodRows = [
  ["Component", "Maximum points", "Definition"],
  ["Consolidation", 20, "10-day high-low range as % of close plus 10D/40D range tightening ratio"],
  ["Higher lows", 15, "Minimum low in newest 10 bars versus minimum low in prior 10 bars"],
  ["Resistance proximity", 20, "Close versus highest high in the prior 20 bars; rewards near-breakouts and fresh breakouts"],
  ["Volume", 15, "Current volume / prior 20D average or prior 5D / prior 20D contraction"],
  ["Momentum/trend", 15, "5D and 20D price change plus close>SMA20 and SMA20>SMA50"],
  ["Weinstein context", 15, "Stored stage when available; otherwise close vs SMA150 and 20D SMA150 slope"],
  ["Overextension penalty", -25, "Penalty above 7/10/15% over SMA20 and above 8% beyond resistance"],
  ["Session completeness", null, "Newest date with >=95% of median symbol coverage across prior sessions"],
  ["Limitation", null, "End-of-day heuristic; no intraday timing, fundamentals, news, or market-regime model"],
];
const methodRange = methods.getRangeByIndexes(0, 0, methodRows.length, 3);
methodRange.values = methodRows;
methodRange.format.font = { name: "Menlo Regular", size: 16, color: "#1F2937" };
methodRange.format.wrapText = true;
methods.getRange("A1:C1").format.fill = "#17365D";
methods.getRange("A1:C1").format.font = { name: "Menlo Regular", size: 16, bold: true, color: "#FFFFFF" };
methods.getRange("A1:A10").format.columnWidthPx = 260;
methods.getRange("B1:B10").format.columnWidthPx = 190;
methods.getRange("C1:C10").format.columnWidthPx = 760;
methodRange.format.autofitRows();

const inspection = await workbook.inspect({ kind: "table", range: `Candidates!A1:W${rowCount}`, include: "values,formulas", tableMaxRows: 5, tableMaxCols: 23, maxChars: 6000 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
for (const [sheetName, range] of [["Candidates", `A1:W${Math.min(rowCount, 21)}`], ["Methodology", "A1:C10"]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `.PriceBreakoutScanner-${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(inspection.ndjson);
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);
