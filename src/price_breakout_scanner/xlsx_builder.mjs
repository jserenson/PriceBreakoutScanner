import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const [dataPath, outputPath, runtimeDirectory] = process.argv.slice(2);
const requireFromRuntime = createRequire(path.join(runtimeDirectory, "entry.cjs"));
const { SpreadsheetFile, Workbook } = requireFromRuntime("@oai/artifact-tool");
const records = JSON.parse(await fs.readFile(dataPath, "utf8"));
const columnName = (number) => {
  let result = "";
  for (let value = number; value > 0; value = Math.floor((value - 1) / 26)) {
    result = String.fromCharCode(65 + ((value - 1) % 26)) + result;
  }
  return result;
};
const columns = [
  ["Rank", "rank"], ["Symbol", "symbol"], ["Company", "company"], ["Date", "date"],
  ["Ignition Score", "score"], ["Market State", "market_state"],
  ["Structure State", "structure_state"], ["Extension State", "extension_state"],
  ["6M Trend Quality %", "trend_quality_6m_pct"],
  ["Positive Structure Bars 6M", "positive_structure_bars_6m"],
  ["Deterioration Flags", "deterioration_flags"],
  ["State", "ignition_state"], ["Price", "price"],
  ["Price / EMA8 %", "price_ema8_distance_pct"], ["Price / EMA21 %", "price_ema21_distance_pct"],
  ["Price / EMA50 %", "price_ema50_distance_pct"], ["Price / EMA8 ATR", "price_ema8_distance_atr"],
  ["EMA8 / EMA21 %", "ema8_ema21_spread_pct"],
  ["Bars Since Ignition", "bars_since_ignition"], ["Move Since Ignition %", "move_since_ignition_pct"],
  ["Bars Since DI+ Cross", "bars_since_di_cross"], ["DI Cross Confirmed", "di_cross_confirmed"],
  ["DI+", "di_plus"], ["DI-", "di_minus"], ["ADX at Cross", "adx_at_cross"],
  ["DI+ Slope 3D", "di_plus_slope_3d"], ["DI+ Slope 5D", "di_plus_slope_5d"],
  ["DI- Slope 3D", "di_minus_slope_3d"], ["DI- Slope 5D", "di_minus_slope_5d"],
  ["DI Spread", "di_spread"], ["DI Spread Slope 3D", "di_spread_slope_3d"],
  ["DI Spread Slope 5D", "di_spread_slope_5d"],
  ["ADX Current", "adx"], ["ADX Slope 5D", "adx_slope_5d"],
  ["ADX State", "adx_state"],
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
  sheet.getRangeByIndexes(1, 12, records.length, 1).format.numberFormat = "$#,##0.00";
  sheet.getRangeByIndexes(1, 13, records.length, 3).format.numberFormat = "0.00\"%\"";
  sheet.getRangeByIndexes(1, 16, records.length, 1).format.numberFormat = "0.00";
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
  ["Intact structure", "Close>EMA8>EMA21>=EMA50 with rising EMA21 and EMA50", "Identify an established bullish ribbon"],
  ["Repairing structure", "Score synchronized recovery evidence across price/EMA alignment, DI slopes, ADX flattening, TMO, both MACDs, and squeeze momentum", "Recognize DX-like repair instead of rejecting it through a Boolean gate"],
  ["DI trajectory", "Track DI+ and DI- slopes over 3 and 5 bars plus widening or narrowing DI spread", "Reject stale crosses whose positive directional pressure has rolled over"],
  ["ADX state", "Classify rising, falling, flattening, or turning up; flattening after decline is constructive during repair", "Avoid requiring already-high ADX before an early move"],
  ["Extension", "Normalize price distance above EMA8 by percent and ATR; also measure price to EMA21/EMA50", "Separate trend quality from entry risk"],
  ["Six-month bar review", "Score close/EMA8/EMA21/EMA50 alignment and each EMA slope on every one of the last 126 trading bars", "Distinguish durable upward structure from a one-day bullish snapshot"],
  ["Deterioration flags", "Flag latest-bar DI+ rollover plus 3-bar weakening in DI, TMO, Squeeze, and both MACD histograms", "Do not rank a positive-but-declining indicator as strong"],
  ["Synchronized ignition", "Recent DI cross + restored structure + at least 4 of price above EMA8, MACD Trend, MACD Timing, TMO, and Squeeze improving", "Require clustered confirmation"],
  ["Lifecycle", "BROKEN -> REPAIRING -> PRIMED -> CONFIRMED -> CONFIRMED_EXTENDED -> WEAKENING", "Describe where the chart is, not just whether it passes"],
  ["Hard rejection", "No synchronized repair evidence, failed recent DI cross, or stale ignition", "Remove damaged moves without discarding legitimate repair"],
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
const lastColumn = columnName(columnCount);
const inspection = await workbook.inspect({ kind: "table", range: `Ignition Candidates!A1:${lastColumn}${rowCount}`, include: "values,formulas", tableMaxRows: 5, tableMaxCols: columnCount, maxChars: 8000 });
for (const [sheetName, range] of [["Ignition Candidates", `A1:${lastColumn}${Math.min(rowCount, 21)}`], ["Methodology", `A1:C${methodRows.length}`]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `.PriceBreakoutScanner-${sheetName.replaceAll(" ", "-")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(inspection.ndjson);
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);
