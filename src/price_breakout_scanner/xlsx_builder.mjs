import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const [dataPath, outputPath, runtimeDirectory, reportMode = "summary"] = process.argv.slice(2);
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
const allColumns = [
  ["Rank", "rank"], ["Symbol", "symbol"], ["Company", "company"], ["Date", "date"],
  ["Ignition Score", "score"], ["Review Action", "review_action"],
  ["Confirmation Needed", "confirmation_needed"],
  ["Entry Readiness", "readiness_state"], ["Momentum Phase", "momentum_phase"], ["Market State", "market_state"],
  ["Structure State", "structure_state"], ["Extension State", "extension_state"],
  ["6M Trend Quality %", "trend_quality_6m_pct"],
  ["Positive Structure Bars 6M", "positive_structure_bars_6m"],
  ["Deterioration Flags", "deterioration_flags"],
  ["State", "ignition_state"], ["Price", "price"],
  ["20/50/200 Structure", "long_term_structure"],
  ["SMA20", "sma20"], ["SMA50", "sma50"], ["SMA200", "sma200"],
  ["SMA20 Slope 5D %", "sma20_slope_5d_pct"],
  ["SMA50 Slope 10D %", "sma50_slope_10d_pct"],
  ["SMA200 Slope 20D %", "sma200_slope_20d_pct"],
  ["Price / SMA200 %", "price_sma200_distance_pct"],
  ["Nearest Support", "nearest_support"],
  ["Nearest Support Type", "nearest_support_type"],
  ["Distance to Support %", "distance_to_support_pct"],
  ["Round Number Below", "round_number_below"],
  ["Round Number Above", "round_number_above"],
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
  ["Squeeze Recent Turn", "squeeze_recent_turn"], ["Squeeze On", "squeeze_on"],
  ["Squeeze Count", "squeeze_count"], ["Squeeze Released", "squeeze_released"],
  ["TMO", "tmo"], ["TMO Signal", "tmo_signal"], ["TMO Slope 3D", "tmo_slope_3d"],
  ["MACD Trend Hist", "macd_trend_hist"], ["MACD Trend Slope 3D", "macd_trend_slope_3d"],
  ["MACD Timing Hist", "macd_timing_hist"], ["MACD Timing Slope 3D", "macd_timing_slope_3d"],
  ["Bars Since Structure Restored", "bars_since_structure_restored"],
  ["EMA8 / EMA50 Spread %", "ema8_ema50_spread_pct"], ["Event Risk", "event_risk"],
  ["Rejection / Watch Reason", "rejection_reason"], ["20D Dollar Volume", "dollar_volume_20d"],
  ["Legacy Atlas Score", "legacy_score"], ["Legacy Grade", "grade"],
];
const watchlistKeys = new Set([
  "rank", "symbol", "company", "date", "score", "review_action",
  "confirmation_needed",
  "readiness_state", "momentum_phase", "structure_state", "extension_state",
  "long_term_structure", "nearest_support", "nearest_support_type",
  "distance_to_support_pct", "round_number_above",
  "trend_quality_6m_pct", "price", "price_ema8_distance_pct",
  "price_ema8_distance_atr", "bars_since_ignition", "di_plus_slope_3d",
  "di_spread_slope_3d", "adx_state", "deterioration_flags", "rejection_reason",
]);
const columns = reportMode === "details"
  ? allColumns.filter(([, key]) => watchlistKeys.has(key))
  : allColumns;
const workbook = Workbook.create();
const summaryName = reportMode === "details" ? "Watchlist Summary" : "Ignition Candidates";
const sheet = workbook.worksheets.add(summaryName);
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
  const formatColumns = (keys, numberFormat) => {
    for (const key of keys) {
      const index = columns.findIndex(([, columnKey]) => columnKey === key);
      if (index >= 0) {
        sheet.getRangeByIndexes(1, index, records.length, 1).format.numberFormat = numberFormat;
      }
    }
  };
  formatColumns(["score"], "0.00");
  formatColumns([
    "price", "sma20", "sma50", "sma200", "nearest_support",
    "round_number_below", "round_number_above", "resistance",
  ], "$#,##0.00");
  formatColumns([
    "trend_quality_6m_pct", "sma20_slope_5d_pct", "sma50_slope_10d_pct",
    "sma200_slope_20d_pct", "price_sma200_distance_pct",
    "distance_to_support_pct", "price_ema8_distance_pct",
    "price_ema21_distance_pct", "price_ema50_distance_pct",
    "ema8_ema21_spread_pct", "move_since_ignition_pct",
    "distance_to_resistance_pct", "breakout_pct", "range_10d_pct",
    "higher_low_pct", "momentum_5d_pct", "momentum_20d_pct",
    "extension_20d_pct", "runup_60d_pct", "ema8_ema50_spread_pct",
  ], "0.00\"%\"");
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
  ["Clean Squeeze v2", "Supplied ThinkScript: length 21, population SD 2.0, simple-average true range 1.5, Mobius Inertia momentum, squeeze state/count/release", "Match the chart's stored-energy and momentum display"],
  ["Chart TMO", "Supplied chart formula: close-close[14], EMA5 twice, with EMA3 signal", "Direction, zero position, and signal relationship"],
  ["MACD Trend", "Chart parameters 24/52/9 histogram and 3-bar slope", "Persistent trend energy"],
  ["MACD Timing", "Chart parameters 3/10/16 histogram and 3-bar slope", "Faster ignition confirmation"],
  ["Intact structure", "Close>EMA8>EMA21>=EMA50 with rising EMA21 and EMA50", "Identify an established bullish ribbon"],
  ["Repairing structure", "Score synchronized recovery evidence across price/EMA alignment, DI slopes, ADX flattening, TMO, both MACDs, and squeeze momentum", "Recognize DX-like repair instead of rejecting it through a Boolean gate"],
  ["DI trajectory", "Track DI+ and DI- slopes over 3 and 5 bars plus widening or narrowing DI spread", "Reject stale crosses whose positive directional pressure has rolled over"],
  ["ADX state", "Classify rising, falling, flattening, or turning up; flattening after decline is constructive during repair", "Avoid requiring already-high ADX before an early move"],
  ["Extension", "Normalize price distance above EMA8 by percent and ATR; also measure price to EMA21/EMA50", "Separate trend quality from entry risk"],
  ["Six-month bar review", "Score close/EMA8/EMA21/EMA50 alignment and each EMA slope on every one of the last 126 trading bars", "Distinguish durable upward structure from a one-day bullish snapshot"],
  ["20/50/200 structure", "Report SMA20/SMA50/SMA200 alignment and multi-day slopes as a separate long-term context layer", "Show whether short-term ignition is supported by the widely watched larger trend"],
  ["Support and round numbers", "Report the nearest support among SMA20/SMA50/SMA200, the 20-day low, and the lower round number; also report the next round number above", "Make pullback risk and psychological trigger levels visible without changing rank"],
  ["Momentum phase", "PRIMED, IGNITING, CONTINUING, DIGESTING, REPAIRING, EXTENDED, or DETERIORATING from the recent bar-by-bar slopes", "Separate fresh entry conditions from positive but mature or fading moves"],
  ["Deterioration flags", "Require multi-bar confirmation for DI+ or MACD timing rollover; also track 3-bar weakening in DI, TMO, Squeeze, and both MACD histograms", "Separate a normal one-bar pause from genuine deterioration"],
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

if (reportMode === "details") {
  for (const record of records) {
    const safeName = String(record.symbol ?? "Ticker").replace(/[\\/?*:[\]]/g, "_").slice(0, 31);
    const detail = workbook.worksheets.add(safeName);
    detail.showGridLines = false;
    detail.freezePanes.freezeRows(1);
    const detailRows = [
      ["Metric", "Value"],
      ["Symbol", record.symbol], ["Company", record.company], ["Data Date", record.date],
      ["Review Action", record.review_action], ["Entry Readiness", record.readiness_state],
      ["Confirmation Needed", record.confirmation_needed],
      ["Momentum Phase", record.momentum_phase], ["Scanner Score", record.score],
      ["Structure", record.structure_state], ["Extension", record.extension_state],
      ["20/50/200 Structure", record.long_term_structure],
      ["SMA20", record.sma20], ["SMA50", record.sma50], ["SMA200", record.sma200],
      ["SMA20 Slope 5D %", record.sma20_slope_5d_pct],
      ["SMA50 Slope 10D %", record.sma50_slope_10d_pct],
      ["SMA200 Slope 20D %", record.sma200_slope_20d_pct],
      ["Price / SMA200 %", record.price_sma200_distance_pct],
      ["Nearest Support", record.nearest_support],
      ["Nearest Support Type", record.nearest_support_type],
      ["Distance to Support %", record.distance_to_support_pct],
      ["Round Number Below", record.round_number_below],
      ["Round Number Above", record.round_number_above],
      ["Price", record.price], ["Price / EMA8 %", record.price_ema8_distance_pct],
      ["Price / EMA21 %", record.price_ema21_distance_pct],
      ["Price / EMA50 %", record.price_ema50_distance_pct],
      ["Price / EMA8 ATR", record.price_ema8_distance_atr],
      ["6M Trend Quality %", record.trend_quality_6m_pct],
      ["Positive Structure Bars 6M", record.positive_structure_bars_6m],
      ["Bars Since Ignition", record.bars_since_ignition],
      ["Move Since Ignition %", record.move_since_ignition_pct],
      ["Bars Since DI+ Cross", record.bars_since_di_cross],
      ["DI+", record.di_plus], ["DI-", record.di_minus], ["DI Spread", record.di_spread],
      ["DI+ Slope 3D", record.di_plus_slope_3d],
      ["DI Spread Slope 3D", record.di_spread_slope_3d],
      ["ADX", record.adx], ["ADX State", record.adx_state],
      ["TMO", record.tmo], ["TMO Slope 3D", record.tmo_slope_3d],
      ["Squeeze Momentum", record.squeeze_momentum],
      ["Squeeze Slope 3D", record.squeeze_slope_3d],
      ["MACD Trend Hist", record.macd_trend_hist],
      ["MACD Trend Slope 3D", record.macd_trend_slope_3d],
      ["MACD Timing Hist", record.macd_timing_hist],
      ["MACD Timing Slope 3D", record.macd_timing_slope_3d],
      ["Deterioration Flags", record.deterioration_flags],
      ["Watch / Rejection Reason", record.rejection_reason],
      ["Event Risk", record.event_risk],
    ];
    const detailRange = detail.getRangeByIndexes(0, 0, detailRows.length, 2);
    detailRange.values = detailRows.map((row) => row.map((value) => value ?? "—"));
    detailRange.format.font = { name: "Menlo Regular", size: 15, color: "#1F2937" };
    detailRange.format.wrapText = true;
    detail.getRange("A1:B1").format.fill = "#17365D";
    detail.getRange("A1:B1").format.font = { name: "Menlo Regular", size: 15, bold: true, color: "#FFFFFF" };
    detail.getRangeByIndexes(0, 0, detailRows.length, 1).format.font = { name: "Menlo Regular", size: 15, bold: true, color: "#17365D" };
    detail.getRangeByIndexes(0, 0, detailRows.length, 1).format.columnWidthPx = 330;
    detail.getRangeByIndexes(0, 1, detailRows.length, 1).format.columnWidthPx = 650;
    detailRange.format.autofitRows();
  }
}

const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
const lastColumn = columnName(columnCount);
const inspection = await workbook.inspect({ kind: "table", range: `${summaryName}!A1:${lastColumn}${rowCount}`, include: "values,formulas", tableMaxRows: 5, tableMaxCols: columnCount, maxChars: 8000 });
for (const [sheetName, range] of [[summaryName, `A1:${lastColumn}${Math.min(rowCount, 21)}`], ["Methodology", `A1:C${methodRows.length}`]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `.PriceBreakoutScanner-${sheetName.replaceAll(" ", "-")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log(inspection.ndjson);
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);
