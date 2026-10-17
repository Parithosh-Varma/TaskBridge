import { GithubMark } from "@/components/ui/GithubMark";
import { PROJECT_FILES } from "@/lib/content";
import { REPO_URL } from "@/lib/github";

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-14 font-mono text-[12px] text-faint sm:px-8 md:grid-cols-[1fr_auto]">
        <div>
          <p className="eyebrow mb-4">Project structure</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
            {PROJECT_FILES.map(([file, role]) => (
              <div key={file} className="contents">
                <dt className="text-paper/80">{file}</dt>
                <dd>{role}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="flex flex-col gap-3 md:items-end md:text-right">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 text-paper/85 transition-colors hover:text-signal"
          >
            <GithubMark size={14} /> Parithosh-Varma/TaskBridge
          </a>
          <p>Licensed under Apache-2.0.</p>
          <p className="mt-auto pt-6 text-paper/60">Claude plans. OpenCode builds.</p>
        </div>
      </div>
    </footer>
  );
}
