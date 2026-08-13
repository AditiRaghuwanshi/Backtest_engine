/**
 * MINIMAL BACKTESTER — STEP 1
 * ----------------------------
 * Goal: prove the core idea works before adding any complexity.
 *
 * What this script does:
 *   1. Reads a CSV of daily OHLC data (from Zerodha historical data)
 *   2. Computes a 20-day moving average
 *   3. Strategy rule:
 *        - If close crosses ABOVE the 20-day average -> BUY (go long)
 *        - If close crosses BELOW the 20-day average -> SELL (exit long)
 *   4. Simulates one trade at a time (no pyramiding, no shorting yet)
 *   5. Prints every trade + a final summary
 *
 * HOW TO RUN:
 *   node backtest.js path/to/your-data.csv
 *
 * Expected CSV columns (case-insensitive, order doesn't matter):
 *   date, open, high, low, close, volume
 * (This matches what Zerodha's historical data API usually gives you.
 *  If your column names are different, just edit the COLUMN MAPPING
 *  section below — that's the only part that depends on your file.)
 */

const fs = require("fs");
const path = require("path");

// ---------- 1. READ AND PARSE THE CSV ----------

function loadCSV(filePath) {
  const raw = fs.readFileSync(filePath, "utf8").trim();
  const lines = raw.split("\n").map((l) => l.trim()).filter(Boolean);

  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());

  // ---- COLUMN MAPPING (edit here if your CSV headers differ) ----
  const idx = {
    date: header.indexOf("date"),
    open: header.indexOf("open"),
    high: header.indexOf("high"),
    low: header.indexOf("low"),
    close: header.indexOf("close"),
  };

  for (const [key, i] of Object.entries(idx)) {
    if (i === -1) {
      throw new Error(
        `Could not find a "${key}" column in your CSV header: ${header.join(", ")}`
      );
    }
  }

  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    rows.push({
      date: cols[idx.date],
      open: parseFloat(cols[idx.open]),
      high: parseFloat(cols[idx.high]),
      low: parseFloat(cols[idx.low]),
      close: parseFloat(cols[idx.close]),
    });
  }

  return rows;
}

// ---------- 2. COMPUTE A SIMPLE MOVING AVERAGE ----------

function addMovingAverage(rows, period) {
  for (let i = 0; i < rows.length; i++) {
    if (i < period - 1) {
      rows[i].sma = null; // not enough data yet
      continue;
    }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      sum += rows[j].close;
    }
    rows[i].sma = sum / period;
  }
  return rows;
}

// ---------- 3. RUN THE STRATEGY (event-by-event loop) ----------

function runBacktest(rows, { smaPeriod = 20, capital = 100000 } = {}) {
  addMovingAverage(rows, smaPeriod);

  let inPosition = false;
  let entryPrice = null;
  let entryDate = null;
  let shares = 0;
  let cash = capital;
  const trades = [];

  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1];
    const curr = rows[i];

    if (curr.sma === null || prev.sma === null) continue; // wait for enough history

    const crossedAbove = prev.close <= prev.sma && curr.close > curr.sma;
    const crossedBelow = prev.close >= prev.sma && curr.close < curr.sma;

    // ENTRY
    if (!inPosition && crossedAbove) {
      inPosition = true;
      entryPrice = curr.close;
      entryDate = curr.date;
      // How many shares can we actually buy with our fixed capital?
      // This is what makes a ₹100 stock and a ₹1,00,000 stock comparable.
      shares = Math.floor(capital / entryPrice);
    }

    // EXIT
    else if (inPosition && crossedBelow) {
      const exitPrice = curr.close;
      const pnl = shares * (exitPrice - entryPrice); // real rupee PnL for this trade
      trades.push({
        entryDate,
        entryPrice,
        exitDate: curr.date,
        exitPrice,
        shares,
        pnl,
      });
      cash += pnl;
      inPosition = false;
      entryPrice = null;
      entryDate = null;
      shares = 0;
    }
  }

  return { trades, endingCash: cash, startingCash: capital };
}

// ---------- 4. PRINT RESULTS (single-file, verbose mode) ----------

function printReport({ trades, startingCash, endingCash }) {
  console.log("\n=== TRADE LOG ===");
  trades.forEach((t, i) => {
    const result = t.pnl >= 0 ? "WIN " : "LOSS";
    console.log(
      `#${i + 1} [${result}]  ${t.entryDate} @ ${t.entryPrice.toFixed(2)}  ->  ${t.exitDate} @ ${t.exitPrice.toFixed(2)}   (${t.shares} shares)   PnL: ${t.pnl.toFixed(2)}`
    );
  });

  printSummaryLine("TOTAL", { trades, startingCash, endingCash });
}

function printSummaryLine(label, { trades, startingCash, endingCash }) {
  const wins = trades.filter((t) => t.pnl > 0);
  const losses = trades.filter((t) => t.pnl <= 0);
  const totalPnl = endingCash - startingCash;
  const winRate = trades.length ? (wins.length / trades.length) * 100 : 0;
  const returnPct = (totalPnl / startingCash) * 100;

  console.log(
    `${label.padEnd(15)} trades: ${String(trades.length).padStart(4)}   ` +
      `winRate: ${winRate.toFixed(1).padStart(5)}%   ` +
      `PnL: ${totalPnl.toFixed(2).padStart(12)}   ` +
      `return: ${returnPct.toFixed(2).padStart(7)}%`
  );

  return { trades: trades.length, wins: wins.length, losses: losses.length, totalPnl };
}

// ---------- 5. BATCH MODE: run across a whole folder of CSVs ----------

function runBatch(folderPath, opts) {
  const files = fs
    .readdirSync(folderPath)
    .filter((f) => f.toLowerCase().endsWith(".csv"));

  if (files.length === 0) {
    console.error(`No CSV files found in ${folderPath}`);
    process.exit(1);
  }

  console.log(`Found ${files.length} CSV files. Running backtest on each...\n`);

  let combinedTrades = 0;
  let combinedWins = 0;
  let combinedLosses = 0;
  let combinedPnl = 0;
  let failedFiles = [];

  for (const file of files) {
    const symbol = path.basename(file, path.extname(file)); // filename without .csv = symbol
    const fullPath = path.join(folderPath, file);

    try {
      const rows = loadCSV(fullPath);
      const result = runBacktest(rows, opts);
      const stats = printSummaryLine(symbol, result);

      combinedTrades += stats.trades;
      combinedWins += stats.wins;
      combinedLosses += stats.losses;
      combinedPnl += stats.totalPnl;
    } catch (err) {
      failedFiles.push({ file, error: err.message });
    }
  }

  console.log("\n" + "=".repeat(80));
  console.log("=== COMBINED (ALL COMPANIES) ===");
  console.log(`Total trades:   ${combinedTrades}`);
  console.log(`Wins / Losses:  ${combinedWins} / ${combinedLosses}`);
  console.log(
    `Win rate:       ${combinedTrades ? ((combinedWins / combinedTrades) * 100).toFixed(1) : 0}%`
  );
  console.log(`Total PnL (sum of all symbols' point moves): ${combinedPnl.toFixed(2)}`);

  if (failedFiles.length) {
    console.log(`\n${failedFiles.length} file(s) failed to process:`);
    failedFiles.forEach((f) => console.log(`  - ${f.file}: ${f.error}`));
  }
}

// ---------- 6. ENTRY POINT ----------

const inputPath = process.argv[2];
if (!inputPath) {
  console.error(
    "Usage:\n" +
      "  Single file:  node backtest.js path/to/one-company.csv\n" +
      "  Whole folder: node backtest.js path/to/folder-of-200-csvs/"
  );
  process.exit(1);
}

const resolvedPath = path.resolve(inputPath);
const stat = fs.statSync(resolvedPath);
const opts = { smaPeriod: 20, capital: 100000 };

if (stat.isDirectory()) {
  runBatch(resolvedPath, opts);
} else {
  const rows = loadCSV(resolvedPath);
  console.log(`Loaded ${rows.length} rows from ${inputPath}`);
  const result = runBacktest(rows, opts);
  printReport(result);
}