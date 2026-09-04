import { ImageResponse } from "next/og";

/**
 * The social preview card, at /opengraph-image. Next wires it into
 * `og:image` (and, via twitter-image, `twitter:image`) automatically.
 *
 * Rendered with Satori, so this is inline styles on flex boxes, not the
 * app's tokens - the dark palette is repeated here as literals. IBM Plex is
 * fetched at build; if that ever fails the card still renders in the
 * default face rather than breaking the route.
 */

export const alt = "LedgerGraph — reconciliation that shows its work.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const C = {
  bg: "#07080c",
  surface: "#0f121a",
  ink: "#f8fafc",
  ink2: "#94a3b8",
  ink3: "#64748b",
  flag: "#0070f3",
  ok: "#10b981",
  line: "#1e2638",
};

async function font(weight: 400 | 600, family: "ibm-plex-sans" | "ibm-plex-mono") {
  const url = `https://cdn.jsdelivr.net/fontsource/fonts/${family}@latest/latin-${weight}-normal.ttf`;
  try {
    const res = await fetch(url);
    return res.ok ? await res.arrayBuffer() : null;
  } catch {
    return null;
  }
}

export default async function Image() {
  const [sans400, sans600, mono600] = await Promise.all([
    font(400, "ibm-plex-sans"),
    font(600, "ibm-plex-sans"),
    font(600, "ibm-plex-mono"),
  ]);

  const fonts = [
    sans400 && { name: "Plex", data: sans400, weight: 400 as const, style: "normal" as const },
    sans600 && { name: "Plex", data: sans600, weight: 600 as const, style: "normal" as const },
    mono600 && { name: "PlexMono", data: mono600, weight: 600 as const, style: "normal" as const },
  ].filter(Boolean) as { name: string; data: ArrayBuffer; weight: 400 | 600; style: "normal" }[];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: C.bg,
          padding: "72px 76px",
          position: "relative",
          fontFamily: "Plex",
          color: C.ink,
        }}
      >
        {/* coral glow */}
        <div
          style={{
            position: "absolute",
            top: -180,
            right: -160,
            width: 680,
            height: 680,
            borderRadius: 680,
            background:
              "radial-gradient(circle, rgba(229,130,116,0.24) 0%, rgba(229,130,116,0) 68%)",
          }}
        />

        {/* wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: 3,
              border: `3px solid ${C.flag}`,
              background: C.surface,
            }}
          />
          <div style={{ fontSize: 34, fontWeight: 600, letterSpacing: -0.5 }}>LedgerGraph</div>
        </div>

        {/* headline */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 82, fontWeight: 600, lineHeight: 1.04, letterSpacing: -2 }}>
            Reconciliation that
          </div>
          <div
            style={{
              fontSize: 82,
              fontWeight: 600,
              lineHeight: 1.04,
              letterSpacing: -2,
              color: C.flag,
            }}
          >
            shows its work.
          </div>
          <div style={{ marginTop: 30, fontSize: 30, color: C.ink2, maxWidth: 900 }}>
            Deterministic matching · grounded AI, citation-verified · no float in the money path.
          </div>
        </div>

        {/* footer */}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 52, fontFamily: "PlexMono", fontWeight: 600, color: C.ok }}>
              0.0000
            </div>
            <div style={{ fontSize: 17, color: C.ink3, letterSpacing: 2, marginTop: 4 }}>
              FALSE-CLEAR RATE · HELD-OUT
            </div>
          </div>
          <div style={{ fontSize: 22, color: C.ink3 }}>Razorpay Hackathon · Track 4</div>
        </div>
      </div>
    ),
    { ...size, fonts: fonts.length ? fonts : undefined },
  );
}
