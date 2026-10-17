export const REPO = "Parithosh-Varma/TaskBridge";
export const REPO_URL = `https://github.com/${REPO}`;
export const README_URL = `${REPO_URL}#readme`;

/** Used when the GitHub API is unreachable or rate-limited. */
const FALLBACK_STARS = 2;

export async function getStarCount(): Promise<number> {
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}`, {
      headers: { Accept: "application/vnd.github+json" },
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) return FALLBACK_STARS;
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "stargazers_count" in data && typeof data.stargazers_count === "number") {
      return data.stargazers_count;
    }
  } catch {
    // Network or timeout — fall through to the fallback.
  }
  return FALLBACK_STARS;
}

export function formatStars(n: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}
