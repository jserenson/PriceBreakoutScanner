import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const [dataPath, outputPath, runtimeDirectory] = process.argv.slice(2);
const requireFromRuntime = createRequire(path.join(runtimeDirectory, "entry.cjs"));
const { SpreadsheetFile, Workbook } = requireFromRuntime("@oai/artifact-tool");
const records = JSON.parse(await fs.readFile(dataPath, "utf8"));
const columns = [
  ["Rank", "rank"], ["Symbol", "symbol"], ["Company", "company"], ["Date", "date"],
  ["Ignition Score", "score"], ["State", "ignition_state"], ["Price", "price"],
  ["Bars Since Ignition", "bars_since_ignition"], ["Move Since Ignition %", "move_since_ignition_pct"],
  ["Bars Since DI+ Cross", "bars_since_di_cross"], ["DI Cross Confirmed", "di_cross_confirmed"],
  ["DI+", "di_plus"], ["DI-", "di_minus"], ["ADX at Cross", "adx_at_cross"],
  ["ADX Current", "adx"], ["ADX Slope 5D", "adx_slope_5d"],
  ["Squeeze Momentum", "squeeze_momentum"], ["Squeeze Slope 3D", "squeeze_slope_3d"],
  ["Squeeze Recent Turn", "squeeze_recent_turn"], ["TMO", "tmo"], ["TMO Slope 3D", "tmo_slope_3d"],
  ["MACD Trend Hist", "macd_trend_hist"], ["MACD Trend Slope 3D", "macd_trend_slope_3d"],
  ["MACD Timing Hist", "macd_timing_hist"], ["MACD Timing Slope 3D", "macd_timing_slope_3d"],
  ["Bars Since Structure Restored", "bars_since_structure_restored"],
  ["EMA8 / EMA50 Spread %", "ema8_ema50_spread_pct"], ["Event Risk", "event_risk"],
  ["Rejection / Watch Reason", "rejection_reason"], ["20D Dollar Volume", "dollar_volume_20d"],
  ["Legacy Atlas Score", "legacy_score"], ["Legacy Grade", "grade"],
];
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Ignition Candidates");
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
  const table = sheet.tables.add(used, true, "IgnitionCandidates");
  table.showBandedRows = true;
  table.showFilterButton = true;
  sheet.getRangeByIndexes(1, 4, records.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 6, records.length, 1).format.numberFormat = "$#,##0.00";
  sheet.getRangeByIndexes(1, 8, records.length, 1).format.numberFormat = "0.00\"%\"";
  sheet.getRangeByIndexes(1, 11, records.length, 14).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 26, records.length, 1).format.numberFormat = "0.00\"%\"";
  sheet.getRangeByIndexes(1, 29, records.length, 1).format.numberFormat = "$#,##0";
  sheet.getRangeByIndexes(1, 30, records.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 4, records.length, 1).conditionalFormats.add("colorScale", {
    thresholds: ["min", "50%", "max"], colors: ["#FECACA", "#FEF3C7", "#BBF7D0"],
  });
}
for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
  const longest = Math.max(...matrix.map((row) => String(row[columnIndex] ?? "").length));
  sheet.getRangeByIndexes(0, columnIndex, rowCount, 1).format.columnWidthPx = Math.min(430, Math.max(100, longest * 13 + 30));
}

const methods = workbook.worksheets.add("Methodology");
methods.showGridLines = false;
methods.freezePanes.freezeRows(1);
const methodRows = [
  ["Feature / rule", "Definition", "Purpose"],
  ["DI+ bullish cross", "Wilder 14 DI+ crosses above DI-; age reported in trading bars", "Primary ignition clock"],
  ["DI confirmation", "DI+ remains above DI- on recent bars and >=70% of bars since cross", "Reject one-bar/failed crosses"],
  ["ADX at cross", "Wilder 14 ADX sampled on DI cross bar; <20 receives early-ignition credit", "ADX is confirmation, not a mandatory gate"],
  ["Squeeze momentum", "20-bar regression of close minus range/SMA midpoint; 3D slope and recent positive turn", "Detect stored energy beginning to expand"],
  ["TMO approximation", "Double-smoothed 14 pairwise close comparisons, scaled -100 to +100", "Direction and position of short-cycle momentum"],
  ["MACD Trend", "12/26/9 histogram and 3-bar slope", "Persistent trend energy"],
  ["MACD Timing", "5/13/4 histogram and 3-bar slope", "Faster ignition confirmation"],
  ["Structure restored", "Close>EMA20, EMA8>EMA20, and EMA20 >=98% of EMA50", "Identify return of bullish price structure"],
  ["Synchronized ignition", "Recent DI cross + restored structure + at least 4 of price above EMA8, MACD Trend, MACD Timing, TMO, and Squeeze improving", "Require clustered confirmation"],
  ["EMERGING", "Ignition <=12 bars, confirmed DI, EMA spread <=8%, >=3 improving energy lanes, and improving MACD", "Default recent-ignition target"],
  ["CONTINUATION", "Ignition 13-30 bars and structure intact; score capped at 54", "Separate established moves from default emerging list"],
  ["WATCH", "Potential pattern without current multi-lane confirmation; score capped at 49", "Possible handle or transition awaiting ignition"],
  ["Hard rejection", "Broken/down structure, failed DI cross, ignition >30 bars, move >20%, or EMA spread >12%", "Remove stale, completed, or damaged moves"],
  ["Event risk", "UNKNOWN: source database has no earnings/event calendar", "Never imply unavailable event safety"],
  ["Limitations", "End-of-day approximations may differ from proprietary chart formulas; no intraday, relative-strength, regime, or earnings model", "Defines appropriate review use"],
];
const methodRange = methods.getRangeByIndexes(0, 0, methodRows.length, 3);
methodRange.values = methodRows;
methodRange.format.font = { name: "Menlo Regular", size: 16, color: "#1F2937" };
methodRange.format.wrapText = true;
methods.getRange("A1:C1").format.fill = "#17365D";
methods.getRange("A1:C1").format.font = { name: "Menlo Regular", size: 16, bold: true, color: "#FFFFFF" };
methods.getRangeByIndexes(0, 0, methodRows.length, 1).format.columnWidthPx = 300;
methods.getRangeByIndexes(0, 1, methodRows.length, 1).format.columnWidthPx = 760;
methods.getRangeByIndexes(0, 2, methodRows.length, 1).format.columnWidthPx = 600;
methodRange.format.autofitRows();

const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
const inspection = await workbook.inspect({ kind: "table", range: `Ignition Candidates!A1:AF${rowCount}`, include: "values,formulas", tableMaxRows: 5, tableMaxCols: 32, maxChars: 8000 });
for (const [sheetName, range] of [["Ignition Candidates", `A1:AF${Math.min(rowCount, 21)}`], ["Methodology", `A1:C${methodRows.length}`]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `.PriceBreakoutScanner-${sheetName.replaceAll(" ", "-")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(inspection.ndjson);
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);
