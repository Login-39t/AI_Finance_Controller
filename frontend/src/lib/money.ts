/**
 * The only place in the frontend that turns paise into a display string.
 *
 * Money crosses the wire as a *string* of minor units - `"12345678"`, not
 * `123456.78` and not `12345678` as a JSON number. Two reasons:
 *
 *   1. A JSON number over 2^53 loses precision silently, and a bank's
 *      daily total in paise gets there faster than people expect.
 *   2. Typing it `string` makes `amount * 1.18` a compile error. The
 *      frontend is then structurally incapable of doing arithmetic on
 *      money, which is the guarantee we actually want - every number a
 *      user sees is one the engine computed.
 *
 * Parsing uses BigInt, never Number.
 */

export type MinorUnits = string;

const EXPONENT: Record<string, number> = {
  INR: 2,
  USD: 2,
  EUR: 2,
  GBP: 2,
  JPY: 0,
  KWD: 3,
};

const SYMBOL: Record<string, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
};

export interface FormatOptions {
  /** Show the currency symbol. Off inside tables where the column header carries it. */
  symbol?: boolean;
  /** Force a leading sign, for bridge components where direction matters. */
  signed?: boolean;
}

/**
 * Indian grouping: last three digits, then pairs.
 * 12345678 -> "1,23,45,678"
 */
function groupIndian(whole: string): string {
  if (whole.length <= 3) return whole;
  const tail = whole.slice(-3);
  let head = whole.slice(0, -3);
  const parts: string[] = [];
  while (head.length > 2) {
    parts.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) parts.unshift(head);
  return [...parts, tail].join(",");
}

function groupWestern(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function formatMinor(
  minor: MinorUnits,
  currency = "INR",
  { symbol = true, signed = false }: FormatOptions = {},
): string {
  const code = currency.toUpperCase();
  const exponent = EXPONENT[code] ?? 2;

  let value: bigint;
  try {
    value = BigInt(minor);
  } catch {
    // A malformed amount must be visible, not rendered as zero. A silent
    // "0.00" in a reconciliation view is worse than an obvious defect.
    return "——";
  }

  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(exponent + 1, "0");

  const whole = exponent ? digits.slice(0, -exponent) : digits;
  const frac = exponent ? digits.slice(-exponent) : "";

  const grouped = code === "INR" ? groupIndian(whole) : groupWestern(whole);
  const body = frac ? `${grouped}.${frac}` : grouped;
  const withSymbol = symbol ? `${SYMBOL[code] ?? code + " "}${body}` : body;

  if (negative) return `-${withSymbol}`;
  if (signed) return `+${withSymbol}`;
  return withSymbol;
}

/** True when the amount is exactly zero, without going through Number. */
export function isZeroMinor(minor: MinorUnits): boolean {
  try {
    return BigInt(minor) === 0n;
  } catch {
    return false;
  }
}

/** Compare two minor amounts. For sorting only - never for accounting. */
export function compareMinor(a: MinorUnits, b: MinorUnits): number {
  try {
    const x = BigInt(a);
    const y = BigInt(b);
    return x < y ? -1 : x > y ? 1 : 0;
  } catch {
    return 0;
  }
}

/** Whole days between an ISO instant and now. Used for case aging. */
export function ageInDays(isoInstant: string): number {
  const then = new Date(isoInstant).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.max(0, Math.floor((Date.now() - then) / 86_400_000));
}

/** "3 Mar 2026" - unambiguous, and short enough for a dense row. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "——";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** "3 Mar 2026, 23:58 IST" - for timelines, where the hour is the story. */
export function formatInstant(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "——";
  const date = d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const time = d.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  });
  return `${date}, ${time} IST`;
}
