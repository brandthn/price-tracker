import type { JSX, SVGProps } from "react";

type PropsType = {
  label: string;
  value: number | string;
  hint?: string;
  Icon: (props: SVGProps<SVGSVGElement>) => JSX.Element;
};

export function OverviewCard({ label, value, hint, Icon }: PropsType) {
  return (
    <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
      <Icon />

      <div className="mt-6">
        <div className="mb-1.5 text-heading-6 font-bold text-dark dark:text-white">
          {value}
        </div>
        <div className="text-sm font-medium text-dark-6">{label}</div>
        {hint ? (
          <div className="mt-1 text-xs text-dark-5 dark:text-dark-6">
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  );
}
