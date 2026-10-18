import { ImageResponse } from "next/og";
import { LOGO_DATA_URI, LOGO_WIDTH, LOGO_HEIGHT } from "@/lib/logo-data";

export const dynamic = "force-static";
export const alt = "TaskBridge — Claude plans. OpenCode builds.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// [packet start, packet length] as fractions of the lane: settled, structured work.
const LANES: [number, number][] = [[0.08, 0.2], [0.42, 0.18], [0.2, 0.16], [0.6, 0.2], [0.3, 0.18]];

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background: "#100c08",
          color: "#efe4cc",
          fontFamily: "monospace",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 30, color: "#9c8c72" }}>
          <img
            src={LOGO_DATA_URI}
            width={Math.round((34 * LOGO_WIDTH) / LOGO_HEIGHT)}
            height={34}
            alt=""
          />
          <span style={{ color: "#efe4cc", fontWeight: 700 }}>TaskBridge</span>
          <span style={{ display: "flex", alignItems: "center", gap: 10, color: "#f2a007", fontSize: 20, letterSpacing: 4 }}>
            <span style={{ width: 12, height: 12, borderRadius: 6, background: "#f2a007" }} />
            LIVE
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 84, fontWeight: 800, letterSpacing: -3, lineHeight: 1.05 }}>
          <span>Claude plans.</span>
          <span style={{ color: "#8fc39a" }}>OpenCode builds.</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", fontSize: 24, color: "#9c8c72", maxWidth: 620 }}>
            Durable SQLite queue · structured results · git-aware diffs
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, width: 300 }}>
            {LANES.map(([start, len], i) => (
              <div key={i} style={{ display: "flex", height: 3, width: "100%", background: "#33291d" }}>
                <div style={{ marginLeft: `${start * 100}%`, width: `${len * 100}%`, height: 3, background: "#8fc39a" }} />
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: 0,
            height: 6,
            background: "linear-gradient(90deg, #e2603a, #f2a007, #8fc39a)",
          }}
        />
      </div>
    ),
    size,
  );
}
