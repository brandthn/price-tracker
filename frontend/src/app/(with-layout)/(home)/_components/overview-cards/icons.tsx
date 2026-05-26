import type { SVGProps } from "react";

type SVGPropsType = SVGProps<SVGSVGElement>;

function Bubble({
  color,
  children,
  ...props
}: SVGPropsType & { color: string; children: React.ReactNode }) {
  return (
    <svg width={58} height={58} viewBox="0 0 58 58" fill="none" {...props}>
      <circle cx={29} cy={29} r={29} fill={color} />
      {children}
    </svg>
  );
}

export function TotalTicketsIcon(props: SVGPropsType) {
  return (
    <Bubble color="#5750F1" {...props}>
      <path
        d="M21 18v22l3-2 3 2 3-2 3 2 3-2 3 2V18l-3 2-3-2-3 2-3-2-3 2-3-2Z"
        stroke="#fff"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      <path
        d="M24 24h10M24 28h10M24 32h6"
        stroke="#fff"
        strokeWidth={1.5}
        strokeLinecap="round"
      />
    </Bubble>
  );
}

export function PendingIcon(props: SVGPropsType) {
  return (
    <Bubble color="#FF9C55" {...props}>
      <circle cx={29} cy={29} r={8} stroke="#fff" strokeWidth={1.5} />
      <path
        d="M29 24v5l3 2"
        stroke="#fff"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Bubble>
  );
}

export function OcrDoneIcon(props: SVGPropsType) {
  return (
    <Bubble color="#18BFFF" {...props}>
      <path
        d="M21 29c0-3 3-7 8-7s8 4 8 7-3 7-8 7-8-4-8-7Z"
        stroke="#fff"
        strokeWidth={1.5}
      />
      <circle cx={29} cy={29} r={3} fill="#fff" />
    </Bubble>
  );
}

export function ValidatedIcon(props: SVGPropsType) {
  return (
    <Bubble color="#22AD5C" {...props}>
      <path
        d="m22 30 5 5 9-12"
        stroke="#fff"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Bubble>
  );
}
