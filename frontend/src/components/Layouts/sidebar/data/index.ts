import * as Icons from "../icons";

export const NAV_DATA = [
  {
    label: "PRICETRACKER",
    items: [
      {
        title: "Dashboard",
        url: "/",
        icon: Icons.HomeIcon,
        items: [],
      },
      {
        title: "Tickets",
        icon: Icons.Table,
        items: [
          { title: "Mes tickets", url: "/tickets" },
          { title: "Uploader un ticket", url: "/tickets/upload" },
        ],
      },
      {
        title: "Catalogue",
        icon: Icons.FourCircle,
        items: [{ title: "Recherche produit", url: "/products" }],
      },
    ],
  },
];
