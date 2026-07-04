import * as Icons from "../icons";

type NavSubItem = { title: string; url: string };

type NavItem = {
  title: string;
  url?: string;
  icon: (props: { className?: string; "aria-hidden"?: boolean | "true" }) => React.ReactNode;
  items: NavSubItem[];
};

type NavSection = { label: string; items: NavItem[] };

// Navigation orientée valeur : observer (données publiques) → mon espace
// (données personnelles). Le jargon pipeline (OCR, statuts techniques)
// n'apparaît jamais ici.
export const NAV_DATA: NavSection[] = [
  {
    label: "Observer",
    items: [
      {
        title: "Observatoire",
        url: "/",
        icon: Icons.PieChart,
        items: [],
      },
      {
        title: "Produits & prix",
        url: "/products",
        icon: Icons.FourCircle,
        items: [],
      },
    ],
  },
  {
    label: "Mon espace",
    items: [
      {
        title: "Mon budget",
        url: "/budget",
        icon: Icons.User,
        items: [],
      },
      {
        title: "Mes tickets",
        url: "/tickets",
        icon: Icons.Table,
        items: [],
      },
    ],
  },
];
