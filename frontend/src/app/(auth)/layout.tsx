import { type PropsWithChildren } from "react";

export default function AuthLayout({ children }: PropsWithChildren) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-2 p-4 dark:bg-[#020d1a]">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-1 dark:bg-gray-dark">
        <div className="mb-6 text-center">
          <h1 className="text-heading-5 font-bold text-primary">PriceTracker</h1>
          <p className="mt-1 text-sm text-dark-6 dark:text-dark-6">
            Suivi de l&apos;inflation consommateur
          </p>
        </div>
        {children}
      </div>
    </main>
  );
}
