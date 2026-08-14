import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const [dataPath, outputPath, runtimeDirectory] = process.argv.slice(2);
const requireFromRuntime = createRequire(path.join(runtimeDirectory, "entry.cjs"));
const { SpreadsheetFile, Workbook } = requireFromRuntime("@oai/artifact-tool");

const records = JSON.parse(await fs.readFile(dataPath, "utf8"));
const columns = [
  ["Rank", "rank"],
  ["Symbol", "symbol"],
  ["Company", "company"],
  ["Date", "date"],
  ["Score", "score"],
  ["Grade", "grade"],
  ["Price", "price"],
  ["Confidence", "confidence"],
  ["Primary Rank", "primary_rank"],
  ["Secondary Rank", "secondary_rank"],
  ["Transition", "transition"],
  ["Setup", "archetype"],
  ["Signal", "description"],
  ["Dollar Volume (50D)", "dollar_volume_50"],
  ["Rank 1 Ignition", "rank1_ignition"],
  ["Momentum Recovering", "momentum_recovering"],
  ["Pullback Completing", "pullback_completing"],
];

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Candidates");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);

const matrix = [
  columns.map(([header]) => header),
  ...records.map((record) => columns.map(([, key]) => record[key] ?? null)),
];
const rowCount = Math.max(matrix.length, 1);
const columnCount = columns.length;
const used = sheet.getRangeByIndexes(0, 0, rowCount, columnCount);
used.values = matrix;
used.format.font = { name: "Menlo Regular", size: 16, color: "#1F2937" };
used.format.verticalAlignment = "center";
used.format.autofitColumns();
used.format.autofitRows();

const header = sheet.getRangeByIndexes(0, 0, 1, columnCount);
header.format.fill = "#17365D";
header.format.font = { name: "Menlo Regular", size: 16, bold: true, color: "#FFFFFF" };
header.format.rowHeight = 28;
header.format.borders = { preset: "outside", style: "thin", color: "#17365D" };

if (records.length > 0) {
  const table = sheet.tables.add(used, true, "BreakoutCandidates");
  table.showBandedRows = true;
  table.showFilterButton = true;

  sheet.getRangeByIndexes(1, 0, records.length, 1).format.numberFormat = "0";
  sheet.getRangeByIndexes(1, 3, records.length, 1).format.numberFormat = "yyyy-mm-dd";
  sheet.getRangeByIndexes(1, 4, records.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(1, 6, records.length, 1).format.numberFormat = "$#,##0.00";
  sheet.getRangeByIndexes(1, 7, records.length, 1).format.numberFormat = "0\"%\"";
  sheet.getRangeByIndexes(1, 8, records.length, 2).format.numberFormat = "0";
  sheet.getRangeByIndexes(1, 13, records.length, 1).format.numberFormat = "$#,##0";
}

// Menlo 16 needs more room than generic autofit provides. Size every column
// from its longest displayed value, with readable minimums and practical caps.
for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
  const longest = Math.max(
    ...matrix.map((row) => String(row[columnIndex] ?? "").length),
  );
  const widthPx = Math.min(600, Math.max(100, longest * 14 + 32));
  sheet.getRangeByIndexes(0, columnIndex, rowCount, 1).format.columnWidthPx = widthPx;
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.save(outputPath);

// Compact structural and visual verification for every generated workbook.
const inspection = await workbook.inspect({
  kind: "table",
  range: `Candidates!A1:Q${rowCount}`,
  include: "values,formulas",
  tableMaxRows: 5,
  tableMaxCols: 17,
  maxChars: 5000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
const preview = await workbook.render({
  sheetName: "Candidates",
  range: `A1:Q${Math.min(rowCount, 21)}`,
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(path.dirname(outputPath), ".PriceBreakoutScanner-preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);
console.log(inspection.ndjson);
console.log(errors.ndjson);
