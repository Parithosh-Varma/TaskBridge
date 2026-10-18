"use client";

import { useEffect, useRef, useState } from "react";
import { useMotionValueEvent, type MotionValue } from "motion/react";
import { DIAGRAM_FALLBACK, DIAGRAM_PARTS, DIAGRAM_SOURCE, DIAGRAM_STAGES } from "@/lib/diagram";

/** Mermaid scopes its generated <style> by this id, so one fixed id per page. */
const RENDER_ID = "tb-architecture";
/** Viewport ratio of the render, kept until the real one is measured — no layout jump. */
const PLACEHOLDER_ASPECT = "1175 / 549";
const STAGES = DIAGRAM_STAGES.length;
/** Progress one part takes to draw in. */
const REVEAL = 0.055;
/** A stage's parts start and settle inside its own slice of the scroll. */
const LEAD = 0.1;
/**
 * A stage's parts fan out over this much of its slice, so the last one finishes drawing exactly
 * as the next stage starts — and the very last part completes before the scroll runs out.
 */
const SPREAD = 1 - LEAD - STAGES * REVEAL;
const SHAPES = "rect, path, polygon, circle, ellipse";
/** The same list, but each one anchored to a node group — a bare `path` would match every edge too. */
const NODE_SHAPES = "g.node rect, g.node path, g.node polygon, g.node circle, g.node ellipse";

type Status = "pending" | "ready" | "error";

interface Part {
  kind: "node" | "edge";
  stage: number;
  tone: string;
  /** Draw progress at which this part starts to appear. */
  at: number;
  /** The element that fades in: a node group, or an edge's label group (the path for a bare edge). */
  shell: SVGElement;
  /** Stroked by the stage highlight: node shapes, or the edge path. */
  shapes: SVGElement[];
  /** Coloured by the stage highlight: node labels, or the edge label text. */
  texts: HTMLElement[];
  /** Node groups: their translate, re-emitted as CSS so the reveal can add a scale. */
  pos?: { x: number; y: number };
  path?: SVGPathElement;
  marker?: string | null;
  len: number;
  // Per-frame state, so a scroll frame only writes what changed.
  t: number;
  markerOn: boolean;
  lit: boolean;
}

const clamp01 = (n: number) => (n < 0 ? 0 : n > 1 ? 1 : n);

const nodeIdOf = (el: Element) => /-flowchart-(.+?)-\d+$/.exec(el.id)?.[1] ?? "";

const CHROME = {
  nodeFill: "var(--panel)",
  nodeStroke: "var(--line)",
  edgeStroke: "var(--rule)",
  nodeText: "var(--paper)",
  edgeText: "var(--faint)",
};

/** Take over mermaid's baked colours: every one is a theme token, so the toggle is free. */
function paint(svg: SVGSVGElement) {
  for (const shape of svg.querySelectorAll<SVGElement>(NODE_SHAPES)) {
    if (shape.closest(".label")) continue; // label background rect: not ours to fill
    shape.style.fill = CHROME.nodeFill;
    shape.style.stroke = CHROME.nodeStroke;
    shape.style.strokeWidth = "1";
    // The "neo" look bakes a bright grey drop shadow on every shape: the card stays flat,
    // and the tone glow of the stage being drawn is the only depth cue.
    shape.style.filter = "none";
  }
  for (const text of svg.querySelectorAll<HTMLElement>("g.node .nodeLabel")) text.style.color = CHROME.nodeText;
  for (const path of svg.querySelectorAll<SVGElement>("g.edgePaths path")) {
    path.style.stroke = CHROME.edgeStroke;
    path.style.filter = "none";
  }
  // Arrowheads inherit from their <marker>, which every edge shares: keep them chrome.
  for (const mark of svg.querySelectorAll<SVGElement>("marker .arrowMarkerPath")) {
    mark.style.fill = CHROME.edgeStroke;
    mark.style.stroke = CHROME.edgeStroke;
  }
  for (const label of svg.querySelectorAll<HTMLElement>("g.edgeLabels .edgeLabel")) label.style.color = CHROME.edgeText;
  // Mermaid paints an opaque chip behind every edge label; the wire should read as a wire.
  for (const chip of svg.querySelectorAll<HTMLElement>("g.edgeLabel, g.edgeLabel div, g.edgeLabel span, g.edgeLabel p")) {
    chip.style.backgroundColor = "transparent";
  }
}

/** Walk the rendered graph once and bind each declared part to its SVG nodes. */
function bindParts(svg: SVGSVGElement): Part[] {
  const seen = new Map<number, number>();
  const totals = DIAGRAM_PARTS.reduce<Record<number, number>>((acc, part) => {
    acc[part.stage] = (acc[part.stage] ?? 0) + 1;
    return acc;
  }, {});
  const parts: Part[] = [];

  for (const declared of DIAGRAM_PARTS) {
    const index = seen.get(declared.stage) ?? 0;
    seen.set(declared.stage, index + 1);
    const at = (declared.stage + LEAD + (SPREAD * index) / totals[declared.stage]) / STAGES;
    const base = { stage: declared.stage, tone: declared.tone, at, len: 0, t: -1, markerOn: false, lit: false };

    if (declared.kind === "edge") {
      const path = svg.querySelector<SVGPathElement>(`g.edgePaths > path[data-id="${declared.id}"]`);
      if (!path) continue;
      const label = svg.querySelector<SVGElement>(`g.edgeLabels g.label[data-id="${declared.id}"]`)?.closest<SVGElement>("g.edgeLabel");
      const len = path.getTotalLength();
      const marker = path.getAttribute("marker-end");
      // The dash is what the reveal draws with; set once, then only its offset moves.
      path.style.strokeDasharray = `${len}`;
      parts.push({
        ...base,
        len,
        kind: "edge",
        shell: label ?? path,
        shapes: [path],
        texts: label ? [...label.querySelectorAll<HTMLElement>("span")] : [],
        path,
        marker,
        // The arrowhead is in the markup from the start: it comes off until the line arrives.
        markerOn: marker != null,
      });
      continue;
    }

    const group = [...svg.querySelectorAll<SVGGElement>("g.node")].find((n) => nodeIdOf(n) === declared.id);
    if (!group) continue;
    const [, x, y] = /translate\(([-\d.]+)[ ,]+([-\d.]+)\)/.exec(group.getAttribute("transform") ?? "") ?? [];
    parts.push({
      ...base,
      kind: "node",
      shell: group,
      shapes: [...group.querySelectorAll<SVGElement>(SHAPES)].filter((s) => !s.closest(".label")),
      texts: [...group.querySelectorAll<HTMLElement>(".nodeLabel")],
      pos: x != null && y != null ? { x: Number(x), y: Number(y) } : undefined,
    });
  }

  return parts;
}

/**
 * Put every part in the state `progress` implies. Scroll-linked and called per frame, so
 * it only ever writes, never measures, and skips parts whose state has not changed.
 */
function draw(parts: Part[], progress: number, complete: boolean) {
  const active = complete ? -1 : Math.min(STAGES - 1, Math.floor(progress * STAGES));

  for (const part of parts) {
    const t = complete ? 1 : clamp01((progress - part.at) / REVEAL);

    if (part.path) {
      part.path.style.strokeDashoffset = `${part.len * (1 - t)}`;
      const on = t >= 1;
      if (on !== part.markerOn) {
        part.markerOn = on;
        if (part.marker) {
          if (on) part.path.setAttribute("marker-end", part.marker);
          else part.path.removeAttribute("marker-end");
        }
      }
    }

    if (t !== part.t) {
      part.t = t;
      part.shell.style.opacity = `${t}`;
      if (part.pos) part.shell.style.transform = `translate(${part.pos.x}px, ${part.pos.y}px) scale(${0.94 + 0.06 * t})`;
    }

    const lit = !complete && t >= 1 && part.stage === active;
    if (lit !== part.lit) {
      part.lit = lit;
      const stroke = lit ? `var(--${part.tone})` : part.kind === "edge" ? CHROME.edgeStroke : CHROME.nodeStroke;
      const text = lit ? `var(--${part.tone})` : part.kind === "edge" ? CHROME.edgeText : CHROME.nodeText;
      for (const shape of part.shapes) {
        shape.style.stroke = stroke;
        // Glow the shape only: a filter on the group would soften the label text with it.
        shape.style.filter = lit
          ? `drop-shadow(0 0 5px color-mix(in srgb, var(--${part.tone}) 55%, transparent))`
          : "none";
      }
      for (const node of part.texts) node.style.color = text;
    }
  }
}

export interface MermaidGraphProps {
  /** Section progress, 0..1. Parts draw in as it advances and un-draw as it retreats. */
  progress: MotionValue<number>;
  /** Reduced motion: render the finished graph, no reveal. */
  complete?: boolean;
  label: string;
  className?: string;
}

/** The README architecture flowchart, rendered by mermaid and revealed by scroll. */
export function MermaidGraph({ progress, complete = false, label, className = "" }: MermaidGraphProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const partsRef = useRef<Part[]>([]);
  const completeRef = useRef(complete);
  const [armed, setArmed] = useState(() => typeof IntersectionObserver === "undefined");
  const [status, setStatus] = useState<Status>("pending");

  useEffect(() => {
    completeRef.current = complete;
    // Reduced motion can turn on after hydration: settle the graph without waiting for a scroll.
    if (partsRef.current.length) draw(partsRef.current, complete ? 1 : progress.get(), complete);
  }, [complete, progress]);

  // Mermaid is a large chunk: fetch it a couple of viewports early, not on load.
  useEffect(() => {
    const box = boxRef.current;
    // No IntersectionObserver: `armed` already started true, so nothing to watch.
    if (!box || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        setArmed(true);
      },
      { rootMargin: "200% 0px" },
    );
    io.observe(box);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!armed) return;
    let cancelled = false;

    (async () => {
      try {
        const [{ default: mermaid }] = await Promise.all([import("mermaid"), document.fonts?.ready]);
        if (cancelled || !hostRef.current || !boxRef.current) return;

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          fontFamily: '"JetBrains Mono", ui-monospace, monospace',
          themeVariables: { fontSize: "16px", edgeLabelBackground: "transparent" },
          flowchart: { htmlLabels: true, curve: "basis", nodeSpacing: 30, rankSpacing: 52, padding: 8 },
        });

        const { svg } = await mermaid.render(RENDER_ID, DIAGRAM_SOURCE);
        const host = hostRef.current;
        const box = boxRef.current;
        if (cancelled || !host || !box) return;

        // Insert, bind and draw before the next paint: no flash of the finished graph.
        host.style.visibility = "hidden";
        host.innerHTML = svg;
        const el = host.querySelector<SVGSVGElement>("svg");
        if (!el) throw new Error("mermaid rendered no svg");
        el.removeAttribute("style");
        box.style.aspectRatio = `${el.viewBox.baseVal.width} / ${el.viewBox.baseVal.height}`;
        partsRef.current = bindParts(el);
        paint(el);
        draw(partsRef.current, completeRef.current ? 1 : progress.get(), completeRef.current);
        host.style.visibility = "";
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [armed, progress]);

  useMotionValueEvent(progress, "change", (v) => draw(partsRef.current, v, completeRef.current));

  return (
    <div
      ref={boxRef}
      role="img"
      aria-label={label}
      style={{ aspectRatio: PLACEHOLDER_ASPECT }}
      className={`tb-mermaid relative max-h-[52svh] min-h-[200px] w-full ${className}`}
    >
      <div ref={hostRef} aria-hidden="true" className={status === "ready" ? "absolute inset-0" : "hidden"} />
      {status !== "ready" && (
        <pre className="font-mono text-[clamp(8px,1.6vw,11px)] leading-[1.9] whitespace-pre text-faint opacity-60">
          {DIAGRAM_FALLBACK}
        </pre>
      )}
    </div>
  );
}
