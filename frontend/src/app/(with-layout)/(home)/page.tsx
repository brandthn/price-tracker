import { Suspense } from "react";
import Link from "next/link";
import { OverviewCardsGroup } from "./_components/overview-cards";
import { OverviewCardsSkeleton } from "./_components/overview-cards/skeleton";
import { RecentTickets } from "./_components/recent-tickets";

export const dynamic = "force-dynamic";

export default function HomePage() {
  return (
    <>
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-heading-4 font-bold text-dark dark:text-white">
            Bienvenue sur PriceTracker
          </h1>
        </div>
        <Link
          href="/tickets/upload"
          className="inline-flex items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
        >
          + Uploader un ticket
        </Link>
      </div>

      <Suspense fallback={<OverviewCardsSkeleton />}>
        <OverviewCardsGroup />
      </Suspense>

      <div className="mt-6 md:mt-9">
        <Suspense
          fallback={
            <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
              <div className="h-32 animate-pulse rounded bg-gray-2 dark:bg-dark-3" />
            </div>
          }
        >
          <RecentTickets />
        </Suspense>
      </div>
    </>
  );
}
