import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useActiveJobs } from "@/hooks/use-active-jobs";
import { useHistory } from "@/hooks/use-history";
import { HeroStage } from "@/components/stage";
import { EmptyStage } from "@/components/empty-stage";
import { AlsoDownloading } from "@/components/also-downloading";
import { Queue } from "@/components/queue";
import { UrlInput } from "@/components/url-input";
import { JobTracker } from "@/components/job-tracker";

export const Route = createFileRoute("/")({ component: NowScreen });

function NowScreen() {
  const activeJobs = useActiveJobs();
  const { history } = useHistory();
  const [trackedJobs, setTrackedJobs] = useState<string[]>([]);

  const stageJob = activeJobs.find((j) => j.state === "running") ?? null;
  const otherRunning = activeJobs.filter(
    (j) => j.job_id !== stageJob?.job_id && j.state === "running"
  );
  const queued = activeJobs.filter((j) => j.state === "queued");

  return (
    <>
      {trackedJobs.map((id) => (
        <JobTracker key={id} jobId={id} onJobCreated={(newId) => setTrackedJobs((prev) => [...prev, newId])} />
      ))}
      {stageJob ? (
        <HeroStage
          snapshot={stageJob}
          activeCount={activeJobs.filter((j) => j.state === "running").length}
        />
      ) : (
        <EmptyStage latest={history[0] ?? null} />
      )}
      <AlsoDownloading jobs={otherRunning} />
      <Queue jobs={queued} />
      <UrlInput onJobCreated={(id) => setTrackedJobs((prev) => [...prev, id])} />
    </>
  );
}
