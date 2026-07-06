import { createFileRoute } from "@tanstack/react-router";
import { useActiveJobs } from "@/hooks/use-active-jobs";
import { useHistory } from "@/hooks/use-history";
import { HeroStage } from "@/components/stage";
import { EmptyStage } from "@/components/empty-stage";
import { RelatedStrip } from "@/components/related-strip";
import { AlsoDownloading } from "@/components/also-downloading";
import { Queue } from "@/components/queue";
import { UrlInput } from "@/components/url-input";

export const Route = createFileRoute("/")({ component: NowScreen });

function NowScreen() {
  const activeJobs = useActiveJobs();
  const { history } = useHistory();

  const stageJob = activeJobs.find((j) => j.state === "running") ?? null;
  // HeroStage only renders urls[0]; pass urls[1:] of the stage job to
  // AlsoDownloading so every URL in a multi-URL batch is visible.
  const stageExtraUrls = stageJob && stageJob.urls.length > 1
    ? [{ ...stageJob, urls: stageJob.urls.slice(1) }]
    : [];
  const otherRunning = activeJobs.filter(
    (j) => j.job_id !== stageJob?.job_id && j.state === "running"
  );
  const queued = activeJobs.filter((j) => j.state === "queued");

  return (
    <>
      {stageJob ? (
        <div key={stageJob.job_id} className="enter-fade">
          <HeroStage
            snapshot={stageJob}
            activeCount={activeJobs.filter((j) => j.state === "running").length}
          />
          <RelatedStrip items={stageJob.urls[0]?.related ?? []} />
        </div>
      ) : (
        <div key="empty" className="enter-fade">
          <EmptyStage latest={history[0] ?? null} />
        </div>
      )}
      <AlsoDownloading jobs={[...stageExtraUrls, ...otherRunning]} stageJobId={stageJob?.job_id} />
      <Queue jobs={queued} />
      <UrlInput />
    </>
  );
}
