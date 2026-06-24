"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getAnalysis, type AnalysisPayload } from "@/lib/api";
import { AnalysisView } from "@/components/AnalysisView";

export default function AnalysisPage() {
  const params = useParams();
  const id = String(params.id);
  // undefined = loading, null = not found / error
  const [data, setData] = useState<AnalysisPayload | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    getAnalysis(id)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (data === undefined) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <span className="eyebrow caret">Loading analysis</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto flex h-[60vh] max-w-md flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-sm text-muted-foreground">
          This analysis isn&apos;t available. It may still be running, or the backend
          restarted (runs are kept in memory).
        </p>
        <Link href="/" className="font-mono text-xs uppercase tracking-[0.1em] text-primary hover:underline">
          ← Start a new query
        </Link>
      </div>
    );
  }

  return <AnalysisView payload={data} />;
}
